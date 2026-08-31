import pytest

from app.repository import _one


class Snapshot:
    exists = True


class AsyncGeneratorTransaction:
    async def get(self, reference):
        assert reference is SENTINEL

        async def snapshots():
            yield Snapshot()

        return snapshots()


SENTINEL = object()


@pytest.mark.asyncio
async def test_transaction_consumes_firestore_async_generator() -> None:
    result = await _one(AsyncGeneratorTransaction(), SENTINEL)
    assert result.exists
