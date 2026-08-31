import pytest

from app.repository import _one


class Snapshot:
    exists = True


class AsyncDocumentReference:
    async def get(self, *, transaction):
        assert transaction is TRANSACTION
        return Snapshot()


TRANSACTION = object()


@pytest.mark.asyncio
async def test_transaction_reads_document_reference_directly() -> None:
    result = await _one(TRANSACTION, AsyncDocumentReference())
    assert result.exists
