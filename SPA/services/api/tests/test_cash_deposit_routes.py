from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1 import cash_deposits as routes
from app.core.auth import require_admin_user
from app.main import app


class CashDeposits:
    def __init__(self) -> None:
        self.created = None

    async def list_unsettled(self, principal, branch_id):
        assert principal.role == "ADMIN"
        assert branch_id == "branch_001"
        return [{"paymentId": "pay_001", "grossAmountSatang": 60_000, "version": 2}]

    async def create(self, **values):
        self.created = values
        return {
            "depositId": "dep_0123456789abcdef01234567",
            "status": "DRAFT",
            "version": 1,
            "totalAmountSatang": 60_000,
        }

    async def get(self, deposit_id, principal):
        assert principal.role == "ADMIN"
        return {"depositId": deposit_id, "status": "QR_ACTIVE", "version": 4}

    async def authorize_evidence(self, **_):
        return SimpleNamespace(
            evidence_id="evidence-001",
            upload_url="https://storage.googleapis.com/signed",
            object_name="cash-deposits/dep/evidence.jpg",
            expires_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )

    async def confirm_evidence(self, **_):
        return {"depositId": "dep_0123456789abcdef01234567", "status": "READY_FOR_QR"}

    async def authorize_evidence_read(self, *_):
        return "https://storage.googleapis.com/read", datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    async def create_attempt(self, **_):
        return {"depositId": "dep_0123456789abcdef01234567", "status": "QR_ACTIVE"}

    async def reconcile(self, *_):
        return {"depositId": "dep_0123456789abcdef01234567", "status": "COMPLETED"}

    async def cancel(self, **_):
        return {"depositId": "dep_0123456789abcdef01234567", "status": "CANCELLED"}


@contextmanager
def client():
    previous = app.dependency_overrides.copy()
    service = CashDeposits()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "admin-001",
        "email": "admin@example.com",
        "role": "ADMIN",
        "branchIds": ["branch_001"],
    }
    app.dependency_overrides[routes.get_cash_deposit_service] = lambda: service
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_create_cash_deposit_preserves_allocation_versions_and_exact_total() -> None:
    with client() as (test_client, service):
        response = test_client.post(
            "/api/v1/admin/cash-deposits",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "branchId": "branch_001",
                "allocations": [{"paymentId": "pay_001", "expectedVersion": 2}],
                "expectedTotalSatang": 60_000,
            },
        )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store, private"
    assert service.created["allocations"][0].expected_version == 2
    assert service.created["expected_total_satang"] == 60_000


def test_cash_deposit_evidence_and_attempt_routes_are_admin_only_contracts() -> None:
    deposit_id = "dep_0123456789abcdef01234567"
    with client() as (test_client, _):
        evidence = test_client.post(
            f"/api/v1/admin/cash-deposits/{deposit_id}/evidence-upload:authorize",
            json={"contentType": "image/jpeg", "sizeBytes": 1234, "sha256": "a" * 64},
        )
        attempt = test_client.post(
            f"/api/v1/admin/cash-deposits/{deposit_id}/attempts",
            headers={"Idempotency-Key": str(uuid4())},
            json={"expectedVersion": 3},
        )
    assert evidence.status_code == 200
    assert evidence.json()["evidenceId"] == "evidence-001"
    assert attempt.status_code == 201
    assert attempt.json()["status"] == "QR_ACTIVE"


def test_cash_deposit_path_and_idempotency_are_rejected_at_boundary() -> None:
    with client() as (test_client, _):
        invalid_path = test_client.get("/api/v1/admin/cash-deposits/not-valid")
        invalid_key = test_client.post(
            "/api/v1/admin/cash-deposits",
            headers={"Idempotency-Key": "not-a-uuid"},
            json={
                "branchId": "branch_001",
                "allocations": [{"paymentId": "pay_001", "expectedVersion": 2}],
                "expectedTotalSatang": 60_000,
            },
        )
    assert invalid_path.status_code == 422
    assert invalid_key.status_code == 422
