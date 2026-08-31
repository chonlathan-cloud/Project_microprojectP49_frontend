from dataclasses import dataclass
from enum import StrEnum
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
    provider_record_id: str | None = None
    provider_document_id: str | None = None
    provider_document_serial: str | None = None
    safe_error_code: str | None = None


async def deliver_export(
    export: ExportProjection,
    settings: Settings,
    client: CashInvoiceClient,
) -> DeliveryOutcome:
    """Deliver one already-claimed export without owning persistence or retry scheduling."""
    try:
        payload = build_cash_invoice_payload(export, settings)
        response = await client.create_cash_invoice(payload)
    except FlowAccountAmbiguousCreateError:
        return DeliveryOutcome(
            state=DeliveryState.RECONCILE_REQUIRED,
            safe_error_code="CREATE_OUTCOME_UNKNOWN",
        )
    except FlowAccountRetryableError:
        return DeliveryOutcome(
            state=DeliveryState.RETRYABLE,
            safe_error_code="PROVIDER_TEMPORARY_FAILURE",
        )
    except (FlowAccountConfigurationError, ValueError):
        return DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            safe_error_code="CONFIGURATION_OR_CONTRACT_ERROR",
        )

    record_id = response.get("recordId")
    document_id = response.get("documentId") or response.get("id")
    document_serial = response.get("documentSerial") or response.get("documentNumber")
    if not record_id and not document_id:
        return DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            safe_error_code="PROVIDER_RESPONSE_ID_MISSING",
        )
    return DeliveryOutcome(
        state=DeliveryState.SYNCED,
        provider_record_id=str(record_id) if record_id else None,
        provider_document_id=str(document_id) if document_id else None,
        provider_document_serial=str(document_serial) if document_serial else None,
    )


async def process_export(export_id: str, settings: Settings, repository: Any) -> DeliveryOutcome:
    """Claim, deliver, and durably classify one export."""
    from app.client import FlowAccountClient, FlowAccountConfigurationError

    claimed = await repository.claim(export_id)
    try:
        async with FlowAccountClient(settings) as client:
            outcome = await deliver_export(claimed.projection, settings, client)
    except FlowAccountConfigurationError:
        outcome = DeliveryOutcome(
            state=DeliveryState.REVIEW_REQUIRED,
            safe_error_code="CONFIGURATION_OR_CONTRACT_ERROR",
        )
    await repository.complete(claimed, outcome)
    return outcome
