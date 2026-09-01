import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from time import perf_counter
from typing import Any, Protocol

from app.client import (
    FlowAccountAmbiguousCreateError,
    FlowAccountConfigurationError,
    FlowAccountRetryableError,
)
from app.contracts import ExportProjection
from app.payload import build_cash_invoice_payload
from app.settings import Settings


class DeliveryState(StrEnum):
    SYNCED = "SYNCED"
    RETRYABLE = "RETRYABLE"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CashInvoiceClient(Protocol):
    async def create_cash_invoice(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    state: DeliveryState
    operation: str | None = None
    provider_record_id: str | None = None
    provider_document_id: str | None = None
    provider_document_serial: str | None = None
    safe_error_code: str | None = None
    payload_digest: str | None = None
    latency_ms: int | None = None
    document_url: str | None = None


async def deliver_export(
    export: ExportProjection,
    settings: Settings,
    client: CashInvoiceClient,
) -> DeliveryOutcome:
    """Deliver one already-claimed export without owning persistence or retry scheduling."""
    payload: dict[str, Any] | None = None
    payload_digest: str | None = None
    started = perf_counter()
    try:
        payload = build_cash_invoice_payload(export, settings)
        payload_digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        response = await client.create_cash_invoice(payload)
    except FlowAccountAmbiguousCreateError:
        return DeliveryOutcome(
            state=DeliveryState.RECONCILE_REQUIRED,
            operation="CREATE_CASH_INVOICE_WITH_PAYMENT",
            safe_error_code="FLOWACCOUNT_CREATE_OUTCOME_UNKNOWN",
            payload_digest=payload_digest,
            latency_ms=round((perf_counter() - started) * 1000),
        )
    except FlowAccountRetryableError:
        return DeliveryOutcome(
            state=DeliveryState.RETRYABLE,
            operation="CREATE_CASH_INVOICE_WITH_PAYMENT",
            safe_error_code="FLOWACCOUNT_DEPENDENCY_UNAVAILABLE",
            payload_digest=payload_digest,
            latency_ms=round((perf_counter() - started) * 1000),
        )
    except (FlowAccountConfigurationError, ValueError):
        return DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            operation="CREATE_CASH_INVOICE_WITH_PAYMENT",
            safe_error_code="FLOWACCOUNT_PAYLOAD_INVALID",
            payload_digest=payload_digest,
            latency_ms=round((perf_counter() - started) * 1000),
        )

    record_id = response.get("recordId")
    document_id = response.get("documentId") or response.get("id")
    document_serial = response.get("documentSerial") or response.get("documentNumber")
    if not record_id and not document_id:
        return DeliveryOutcome(
            state=DeliveryState.RECONCILE_REQUIRED,
            operation="CREATE_CASH_INVOICE_WITH_PAYMENT",
            safe_error_code="FLOWACCOUNT_CREATE_OUTCOME_UNKNOWN",
            payload_digest=payload_digest,
            latency_ms=round((perf_counter() - started) * 1000),
        )
    return DeliveryOutcome(
        state=DeliveryState.SYNCED,
        operation="CREATE_CASH_INVOICE_WITH_PAYMENT",
        provider_record_id=str(record_id) if record_id else None,
        provider_document_id=str(document_id) if document_id else None,
        provider_document_serial=str(document_serial) if document_serial else None,
        payload_digest=payload_digest,
        latency_ms=round((perf_counter() - started) * 1000),
    )


async def reconcile_export(
    export: ExportProjection,
    client: Any,
) -> DeliveryOutcome | None:
    try:
        matches = await client.find_cash_invoices(
            external_document_id=export.external_document_id,
            accounting_date=export.accounting_date.isoformat(),
        )
    except FlowAccountRetryableError:
        return DeliveryOutcome(
            state=DeliveryState.RECONCILE_REQUIRED,
            operation="RECONCILE_CASH_INVOICE",
            safe_error_code="FLOWACCOUNT_DEPENDENCY_UNAVAILABLE",
        )
    except FlowAccountConfigurationError:
        return DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            operation="RECONCILE_CASH_INVOICE",
            safe_error_code="FLOWACCOUNT_PAYLOAD_INVALID",
        )
    if not matches:
        return None
    if len(matches) != 1:
        return DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            operation="RECONCILE_CASH_INVOICE",
            safe_error_code=(
                "FLOWACCOUNT_DUPLICATE_REVIEW_REQUIRED"
                if len(matches) > 1
                else "FLOWACCOUNT_DOCUMENT_NOT_FOUND"
            ),
        )
    match = matches[0]
    return DeliveryOutcome(
        state=DeliveryState.SYNCED,
        operation="RECONCILE_CASH_INVOICE",
        provider_record_id=str(match.get("recordId") or "") or None,
        provider_document_id=str(match.get("documentId") or match.get("id") or "") or None,
        provider_document_serial=str(
            match.get("documentSerial") or match.get("documentNumber") or ""
        )
        or None,
    )


async def process_export(
    export_id: str,
    settings: Settings,
    repository: Any,
    client: Any | None = None,
) -> DeliveryOutcome:
    """Claim, deliver, and durably classify one export."""
    from app.client import FlowAccountClient, FlowAccountConfigurationError

    claimed = await repository.claim(export_id)
    try:
        if client is not None:
            if claimed.reconcile_only:
                outcome = await reconcile_export(claimed.projection, client)
                if outcome is None:
                    outcome = await deliver_export(claimed.projection, settings, client)
            else:
                outcome = await deliver_export(claimed.projection, settings, client)
        else:
            async with FlowAccountClient(settings) as owned_client:
                if claimed.reconcile_only:
                    outcome = await reconcile_export(claimed.projection, owned_client)
                    if outcome is None:
                        outcome = await deliver_export(
                            claimed.projection, settings, owned_client
                        )
                else:
                    outcome = await deliver_export(
                        claimed.projection, settings, owned_client
                    )
    except FlowAccountConfigurationError:
        outcome = DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            operation=(
                "RECONCILE_CASH_INVOICE"
                if claimed.reconcile_only
                else "CREATE_CASH_INVOICE_WITH_PAYMENT"
            ),
            safe_error_code="FLOWACCOUNT_AUTH_CONFIG_INVALID",
        )
    await repository.complete(claimed, outcome)
    return outcome
