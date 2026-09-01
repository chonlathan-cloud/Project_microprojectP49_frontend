from datetime import UTC, datetime

import pytest

from app.core.types import PaymentAttemptStatus
from app.infrastructure.firestore_payments import (
    _charge_link_attempt_updates,
    _one,
    _snapshots,
)
from app.integrations.beam import BeamCharge


class AsyncGeneratorTransaction:
    async def get(self, reference):
        assert reference is SENTINEL

        async def snapshots():
            yield "first"
            yield "second"

        return snapshots()


SENTINEL = object()
TRANSACTION = object()


class AsyncDocumentReference:
    async def get(self, *, transaction):
        assert transaction is TRANSACTION
        return "document"


@pytest.mark.asyncio
async def test_payment_transaction_consumes_firestore_async_generator() -> None:
    result = await _snapshots(AsyncGeneratorTransaction(), SENTINEL)
    assert result == ["first", "second"]


@pytest.mark.asyncio
async def test_payment_transaction_reads_document_reference_directly() -> None:
    result = await _one(TRANSACTION, AsyncDocumentReference())
    assert result == "document"


def test_pending_charge_link_does_not_activate_unknown_attempt_without_action() -> None:
    now = datetime(2026, 9, 1, 9, 16, tzinfo=UTC)
    updates = _charge_link_attempt_updates(
        {"status": PaymentAttemptStatus.CREATE_UNKNOWN, "version": 2},
        BeamCharge(
            charge_id="ch_001",
            merchant_id="merchant_001",
            reference_id="SPA-PAY-pay_001-pat_001",
            status="PENDING",
            currency="THB",
            amount=67_000,
            transaction_time=None,
        ),
        now,
    )

    assert updates["providerChargeId"] == "ch_001"
    assert updates["version"] == 3
    assert "status" not in updates
    assert "actionRequired" not in updates
