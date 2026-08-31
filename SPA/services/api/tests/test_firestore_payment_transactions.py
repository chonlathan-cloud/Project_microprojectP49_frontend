import pytest

from app.infrastructure.firestore_payments import _snapshots


class AsyncGeneratorTransaction:
    async def get(self, reference):
        assert reference is SENTINEL

        async def snapshots():
            yield "first"
            yield "second"

        return snapshots()


SENTINEL = object()


@pytest.mark.asyncio
async def test_payment_transaction_consumes_firestore_async_generator() -> None:
    result = await _snapshots(AsyncGeneratorTransaction(), SENTINEL)
    assert result == ["first", "second"]
