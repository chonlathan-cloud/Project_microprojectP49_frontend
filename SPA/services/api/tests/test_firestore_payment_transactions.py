import pytest

from app.infrastructure.firestore_payments import _one, _snapshots


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
