from typing import Any

import pytest

from app.client import (
    FlowAccountAmbiguousCreateError,
    FlowAccountRetryableError,
)
from app.processor import DeliveryState, deliver_export, reconcile_export
from tests.test_payload import export, settings


class StubClient:
    def __init__(self, result: dict[str, Any] | Exception):
        self.result = result

    async def create_cash_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ReconcileClient:
    def __init__(self, matches: tuple[dict[str, Any], ...]) -> None:
        self.matches = matches

    async def find_cash_invoices(self, **_: str) -> tuple[dict[str, Any], ...]:
        return self.matches


@pytest.mark.asyncio
async def test_success_persists_provider_identifiers() -> None:
    outcome = await deliver_export(
        export(),
        settings(),
        StubClient({"recordId": "record-001", "documentSerial": "CAI-001"}),
    )
    assert outcome.state is DeliveryState.SYNCED
    assert outcome.provider_record_id == "record-001"
    assert outcome.provider_document_serial == "CAI-001"


@pytest.mark.asyncio
async def test_unknown_create_outcome_requires_reconciliation() -> None:
    outcome = await deliver_export(
        export(),
        settings(),
        StubClient(FlowAccountAmbiguousCreateError("timeout")),
    )
    assert outcome.state is DeliveryState.RECONCILE_REQUIRED


@pytest.mark.asyncio
async def test_transient_failure_retries_but_missing_ids_reconcile() -> None:
    retry = await deliver_export(
        export(),
        settings(),
        StubClient(FlowAccountRetryableError("429")),
    )
    invalid = await deliver_export(export(), settings(), StubClient({"message": "created"}))
    assert retry.state is DeliveryState.RETRYABLE
    assert invalid.state is DeliveryState.RECONCILE_REQUIRED


@pytest.mark.asyncio
async def test_reconciliation_distinguishes_absent_exact_and_duplicate() -> None:
    absent = await reconcile_export(export(), ReconcileClient(()))
    exact = await reconcile_export(
        export(),
        ReconcileClient(({"recordId": 1, "documentId": 2, "documentSerial": "CA-1"},)),
    )
    duplicate = await reconcile_export(
        export(), ReconcileClient(({"documentId": 1}, {"documentId": 2}))
    )
    assert absent is None
    assert exact is not None and exact.state is DeliveryState.SYNCED
    assert exact.provider_document_serial == "CA-1"
    assert duplicate is not None and duplicate.state is DeliveryState.REVIEW_REQUIRED
    assert duplicate.safe_error_code == "FLOWACCOUNT_DUPLICATE_REVIEW_REQUIRED"
