from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1 import accounting as accounting_routes
from app.core.auth import require_admin_user
from app.core.settings import Settings
from app.main import app


class AccountingRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.historical_records: list[dict[str, Any]] = []

    def list_payments(self, **_: Any) -> dict[str, Any]:
        return {
            "items": [],
            "nextPageToken": None,
            "summary": {
                "scope": "CURRENT_PAGE",
                "paidGrossSatang": 0,
                "beamGrossSatang": 0,
                "cashGrossSatang": 0,
                "bankTransferGrossSatang": 0,
                "syncedCount": 0,
                "attentionCount": 0,
            },
        }

    def list_pending_historical(self, *, branch_id: str) -> dict[str, Any]:
        assert branch_id == "branch_001"
        return {
            "items": [
                {
                    "bookingId": "BK-20260820-001",
                    "grossAmountSatang": 35_000,
                    "version": 1,
                }
            ],
            "total": 1,
        }

    def record_historical_payment(self, **values: Any) -> dict[str, Any]:
        self.historical_records.append(values)
        return {
            "bookingId": values["booking_public_id"],
            "paymentStatus": "PAID",
            "paymentSource": values["payment_source"],
        }

    def detail(self, payment_id: str, *, branch_ids: tuple[str, ...]) -> dict[str, Any]:
        return {"payment": {"paymentId": payment_id, "branchIds": branch_ids}, "attempts": []}

    def eligible_export_ids(
        self, *, branch_ids: tuple[str, ...], operation: str
    ) -> tuple[str, ...]:
        assert branch_ids == ("branch_001",)
        assert operation == "SYNC"
        return ("fa_backlog",)

    def create_run(self, **values: Any) -> tuple[str, bool]:
        self.created.append(values)
        return "run_001", True

    def get_run(self, run_id: str, *, branch_ids: tuple[str, ...]) -> dict[str, Any]:
        return {"runId": run_id, "branchIds": list(branch_ids), "status": "RUNNING"}


class Tasks:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def enqueue_run(self, run_id: str) -> bool:
        self.run_ids.append(run_id)
        return True


@contextmanager
def accounting_client(
    role: str = "ADMIN",
) -> Iterator[tuple[TestClient, AccountingRepository, Tasks]]:
    previous = app.dependency_overrides.copy()
    repository = AccountingRepository()
    tasks = Tasks()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "operator-001",
        "role": role,
        "branchIds": ["branch_001"],
    }
    app.dependency_overrides[accounting_routes.get_accounting_repository] = lambda: repository
    app.dependency_overrides[accounting_routes.get_task_enqueuer] = lambda: tasks
    try:
        yield TestClient(app), repository, tasks
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_staff_can_read_accounting_without_sync_permission() -> None:
    with accounting_client("STAFF") as (client, _, __):
        response = client.get(
            "/api/v1/admin/payments?branchId=branch_001&dateFrom=2026-08-31&dateTo=2026-08-31"
        )
        detail = client.get("/api/v1/admin/payments/pay_001")
    assert response.status_code == 200
    assert response.json()["permissions"] == {
        "read": True,
        "sync": False,
        "cashDeposit": False,
    }
    assert response.json()["summary"]["scope"] == "CURRENT_PAGE"
    assert detail.status_code == 200


def test_staff_cannot_create_accounting_run() -> None:
    with accounting_client("STAFF") as (client, _, __):
        response = client.post(
            "/api/v1/admin/accounting-sync-runs",
            headers={"Idempotency-Key": str(uuid4())},
            json={"exportIds": ["fa_001"]},
        )
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_admin_can_classify_pending_historical_payment() -> None:
    with accounting_client() as (client, repository, _):
        queue = client.get(
            "/api/v1/admin/historical-accounting-candidates?branchId=branch_001"
        )
        response = client.post(
            "/api/v1/admin/historical-accounting-candidates/BK-20260820-001:record",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "paymentSource": "BANK_TRANSFER",
                "bankAccountKey": "kbank-6073-a",
                "paidAt": "2026-08-20T15:00:00+07:00",
                "expectedVersion": 1,
                "confirmed": True,
            },
        )
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    assert response.status_code == 200, response.text
    assert response.json()["paymentSource"] == "BANK_TRANSFER"
    assert repository.historical_records[0]["booking_public_id"] == "BK-20260820-001"
    assert repository.historical_records[0]["payment_source"] == "BANK_TRANSFER"
    assert repository.historical_records[0]["bank_account_key"] == "kbank-6073-a"


def test_admin_payment_options_expose_safe_labels_only(monkeypatch) -> None:
    monkeypatch.setattr(
        accounting_routes,
        "get_settings",
        lambda: Settings(
            accounting_bank_accounts_json=(
                '[{"key":"kbank-6073-a","bankAccountId":"462850",'
                '"transferBankAccountId":"2","labelTh":"KBank ••••6073 (บัญชี A)",'
                '"labelEn":"KBank ••••6073 (Account A)"}]'
            )
        ),
    )
    with accounting_client() as (client, _, __):
        response = client.get("/api/v1/admin/manual-payment-options")

    assert response.status_code == 200
    assert response.json() == {
        "bankTransferAccounts": [
            {
                "key": "kbank-6073-a",
                "labelTh": "KBank ••••6073 (บัญชี A)",
                "labelEn": "KBank ••••6073 (Account A)",
            }
        ]
    }
    assert "462850" not in response.text


def test_staff_cannot_classify_historical_payment() -> None:
    with accounting_client("STAFF") as (client, _, __):
        queue = client.get("/api/v1/admin/historical-accounting-candidates")
        response = client.post(
            "/api/v1/admin/historical-accounting-candidates/BK-20260820-001:record",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "paymentSource": "CASH",
                "paidAt": "2026-08-20T15:00:00+07:00",
                "expectedVersion": 1,
                "confirmed": True,
            },
        )
    assert queue.status_code == 403
    assert response.status_code == 403


def test_admin_selected_run_is_async_and_idempotent() -> None:
    with accounting_client() as (client, repository, tasks):
        response = client.post(
            "/api/v1/admin/accounting-sync-runs",
            headers={"Idempotency-Key": str(uuid4())},
            json={"exportIds": ["fa_001", "fa_001", "fa_002"]},
        )
    assert response.status_code == 202
    assert response.json() == {"runId": "run_001", "created": True, "status": "PENDING"}
    assert repository.created[0]["export_ids"] == ("fa_001", "fa_002")
    assert repository.created[0]["operation"] == "SYNC"
    assert tasks.run_ids == ["run_001"]


def test_admin_backlog_and_reconcile_use_the_same_run_engine() -> None:
    with accounting_client() as (client, repository, tasks):
        backlog = client.post(
            "/api/v1/admin/accounting-sync-runs",
            headers={"Idempotency-Key": str(uuid4())},
            json={"filter": {"branchId": "branch_001"}},
        )
        reconcile = client.post(
            "/api/v1/admin/accounting-exports/fa_review:reconcile",
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert backlog.status_code == 202
    assert reconcile.status_code == 202
    assert repository.created[0]["export_ids"] == ("fa_backlog",)
    assert repository.created[1]["operation"] == "RECONCILE"
    assert tasks.run_ids == ["run_001", "run_001"]


def test_run_scope_and_idempotency_contract_are_validated() -> None:
    with accounting_client() as (client, _, __):
        both = client.post(
            "/api/v1/admin/accounting-sync-runs",
            headers={"Idempotency-Key": str(uuid4())},
            json={"exportIds": ["fa_001"], "filter": {"branchId": "branch_001"}},
        )
        invalid_key = client.post(
            "/api/v1/admin/accounting-sync-runs",
            headers={"Idempotency-Key": "not-a-uuid"},
            json={"exportIds": ["fa_001"]},
        )
    assert both.status_code == 422
    assert invalid_key.status_code == 422
    assert invalid_key.json()["code"] == "VALIDATION_FAILED"
