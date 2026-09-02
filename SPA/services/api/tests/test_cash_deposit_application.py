from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.application.cash_deposits import CashDepositService, PreparedCashDepositAttempt
from app.core.types import AppRole
from app.domains.identity.models import AdminPrincipal


class ReplayRepository:
    def __init__(self) -> None:
        self.get_count = 0

    async def begin_attempt(self, **_) -> PreparedCashDepositAttempt:
        return PreparedCashDepositAttempt(
            deposit_id="dep_0123456789abcdef01234567",
            attempt_id="cda_0123456789abcdef012345",
            total_amount_satang=60_000,
            currency="THB",
            provider_reference_id="SPA-CASH-DEP-existing",
            provider_idempotency_key="provider-key",
            requested_expires_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            is_replay=True,
        )

    async def get(self, deposit_id: str, *, branch_ids: tuple[str, ...]) -> dict:
        self.get_count += 1
        assert deposit_id == "dep_0123456789abcdef01234567"
        assert branch_ids == ("branch_001",)
        return {
            "depositId": deposit_id,
            "status": "QR_ACTIVE",
            "attempt": {"attemptId": "cda_0123456789abcdef012345", "status": "ACTIVE"},
        }


@pytest.mark.asyncio
async def test_attempt_idempotency_replay_returns_persisted_state_without_creating_charge() -> None:
    repository = ReplayRepository()
    settings = SimpleNamespace(cash_deposit_qr_expiry_minutes=30)
    service = CashDepositService(repository, object(), settings)  # type: ignore[arg-type]
    service._require_enabled = lambda: None  # type: ignore[method-assign]

    result = await service.create_attempt(
        deposit_id="dep_0123456789abcdef01234567",
        principal=AdminPrincipal(
            uid="admin-001",
            email="admin@example.com",
            role=AppRole.ADMIN,
            branch_ids=("branch_001",),
        ),
        expected_version=3,
        idempotency_key="6efc684f-3d86-402e-a46d-62fd75c62d6c",
    )

    assert result["status"] == "QR_ACTIVE"
    assert repository.get_count == 1
    assert "imageBase64" not in result["attempt"]
