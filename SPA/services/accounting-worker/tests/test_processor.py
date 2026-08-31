from typing import Any

import pytest

from app.client import (
    FlowAccountAmbiguousCreateError,
    FlowAccountRetryableError,
)
from app.processor import DeliveryState, deliver_export
from tests.test_payload import export, settings


class StubClient:
    def __init__(self, result: dict[str, Any] | Exception):
        self.result = result

    async def create_cash_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


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
async def test_transient_failure_is_retryable_but_invalid_response_requires_review() -> None:
    retry = await deliver_export(
        export(),
        settings(),
        StubClient(FlowAccountRetryableError("429")),
    )
    invalid = await deliver_export(export(), settings(), StubClient({"message": "created"}))
    assert retry.state is DeliveryState.RETRYABLE
    assert invalid.state is DeliveryState.REVIEW_REQUIRED
