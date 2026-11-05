from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.v1 import compensation
from app.core.auth import require_admin_user
from app.infrastructure.firestore import get_firestore_client
from app.main import app


class Snapshot:
    def __init__(self, ref):
        self.id, self.reference = ref.id, ref
        self.data = deepcopy(ref.db.data[ref.collection].get(ref.id))
        self.exists = self.data is not None

    def to_dict(self):
        return deepcopy(self.data)


class Document:
    def __init__(self, db, collection, document_id):
        self.db, self.collection, self.id = db, collection, document_id

    def get(self, transaction=None):
        if transaction:
            transaction.reads.append((self.collection, self.id))
        return Snapshot(self)


class Query:
    def __init__(self, db, collection, filters=(), count=None):
        self.db, self.collection, self.filters, self.count = db, collection, filters, count

    def document(self, document_id=None):
        return Document(
            self.db, self.collection, document_id or f"audit-{len(self.db.data[self.collection])}"
        )

    def where(self, field, operator, value):
        return Query(
            self.db, self.collection, (*self.filters, (field, operator, value)), self.count
        )

    def limit(self, count):
        return Query(self.db, self.collection, self.filters, count)

    def stream(self, transaction=None):
        results = []
        for key, data in self.db.data[self.collection].items():
            matches = True
            for field, operator, value in self.filters:
                actual = data
                for part in field.split("."):
                    actual = actual.get(part) if isinstance(actual, dict) else None
                matches &= actual in value if operator == "in" else actual == value
            if matches:
                results.append(Document(self.db, self.collection, key).get(transaction))
        return results[: self.count]


class Transaction:
    def __init__(self):
        self.writes, self.reads = [], []

    def update(self, ref, data):
        self.writes.append((ref, data, True))

    def set(self, ref, data):
        self.writes.append((ref, data, False))

    def commit(self):
        for ref, data, merge in self.writes:
            if merge:
                ref.db.data[ref.collection][ref.id].update(data)
            else:
                ref.db.data[ref.collection][ref.id] = data


class Database:
    def __init__(self):
        self.data = {
            name: {}
            for name in (
                "therapists",
                "bookings",
                "booking_line_items",
                "audit_events",
                "therapist_attendance",
                "therapist_guarantee_rates",
                "therapist_payouts",
                "service_settlements",
                "therapist_compensation_adjustments",
            )
        }
        self.data["therapists"]["t1"] = {
            "therapistId": "t1",
            "displayName": "คุณนิด",
            "branchId": "branch_001",
            "active": True,
            "version": 3,
            "dailyGuaranteeSatang": 40000,
        }
        self.last_transaction = None

    def collection(self, name):
        return Query(self, name)

    def transaction(self):
        self.last_transaction = Transaction()
        return self.last_transaction


@pytest.fixture
def database(monkeypatch):
    db = Database()

    def transactional(fn):
        def run(tx):
            result = fn(tx)
            tx.commit()
            return result

        return run

    monkeypatch.setattr(firestore, "transactional", transactional)
    app.dependency_overrides[require_admin_user] = lambda: {"uid": "admin-1", "role": "ADMIN"}
    app.dependency_overrides[get_firestore_client] = lambda: db
    yield db
    app.dependency_overrides.clear()


def change_status(active=False, version=3, reason="  เลิกทำงานกับร้าน  "):
    return TestClient(app).patch(
        "/api/v1/admin/therapists/t1/status",
        json={
            "active": active,
            "expectedVersion": version,
            "reason": reason,
        },
    )


def test_status_change_is_audited_and_reactivation_preserves_identity_and_terms(database):
    response = change_status()
    assert response.status_code == 200
    record = database.data["therapists"]["t1"]
    assert record["active"] is False
    assert record["dailyGuaranteeSatang"] == 40000
    assert record["statusChangedBy"] == "admin-1"
    assert record["statusReason"] == "เลิกทำงานกับร้าน"
    event = next(iter(database.data["audit_events"].values()))
    assert event["oldActive"] is True and event["newActive"] is False
    assert event["reason"] == record["statusReason"]
    assert change_status(active=True, version=4, reason="กลับมาทำงาน").status_code == 200
    assert list(database.data["therapists"]) == ["t1"]
    assert record["version"] == 5 and record["active"] is True


@pytest.mark.parametrize("role,expected", [("STAFF", 403), (None, 401)])
def test_status_change_requires_admin(database, role, expected):
    if role:
        app.dependency_overrides[require_admin_user] = lambda: {"uid": "staff", "role": role}
    else:
        app.dependency_overrides.pop(require_admin_user)
    assert change_status().status_code == expected
    assert database.data["therapists"]["t1"]["active"] is True
    assert not database.data["audit_events"]


@pytest.mark.parametrize("version,reason,expected", [(2, "ออก", 409), (3, "  ", 422)])
def test_invalid_status_change_writes_nothing(database, version, reason, expected):
    before = deepcopy(database.data)
    assert change_status(version=version, reason=reason).status_code == expected
    assert database.data == before


def test_missing_therapist_is_not_created(database):
    database.data["therapists"].clear()
    assert change_status().status_code == 404


@pytest.mark.parametrize(
    "status,addon", [("CONFIRMED", False), ("IN_SERVICE", False), ("IN_SERVICE", True)]
)
def test_open_assignments_block_departure_including_added_services(database, status, addon):
    database.data["bookings"]["booking-1"] = {
        "publicBookingId": "BK-001",
        "status": status,
        "branchId": "branch_001",
        "therapistIds": [] if addon else ["t1"],
    }
    if addon:
        database.data["booking_line_items"]["line-1"] = {
            "bookingDocId": "booking-1",
            "assignment": {"therapistId": "t1"},
        }
    before = deepcopy(database.data)
    response = change_status()
    assert response.status_code == 409
    assert response.json()["code"] == "THERAPIST_HAS_OPEN_BOOKINGS"
    assert "BK-001" in response.json()["detail"]
    assert database.data == before


def test_completed_history_does_not_block_departure(database):
    database.data["bookings"]["booking-1"] = {
        "publicBookingId": "BK-001",
        "status": "COMPLETED",
        "branchId": "branch_001",
        "therapistIds": ["t1"],
    }
    assert change_status().status_code == 200
    assert database.data["bookings"]["booking-1"]["therapistIds"] == ["t1"]


@pytest.mark.parametrize(
    "active,status,expected",
    [(False, "CONFIRMED", 422), (True, "IN_SERVICE", 409), (True, "CONFIRMED", 200)],
)
def test_assignment_checks_current_therapist_inside_transaction(database, active, status, expected):
    database.data["therapists"]["t1"]["active"] = active
    database.data["bookings"]["booking-1"] = {
        "publicBookingId": "BK-001",
        "status": status,
        "branchId": "branch_001",
        "pax": 1,
        "version": 2,
    }
    response = TestClient(app).put(
        "/api/v1/admin/bookings/BK-001/assignments",
        json={
            "therapistIds": ["t1"],
            "expectedVersion": 2,
        },
    )
    assert response.status_code == expected
    if expected == 200:
        assert ("therapists", "t1") in database.last_transaction.reads
        assert database.data["bookings"]["booking-1"]["therapistName"] == "คุณนิด"
    else:
        assert database.data["bookings"]["booking-1"]["version"] == 2


def test_departed_therapist_cannot_be_marked_present_today(database):
    database.data["therapists"]["t1"].update(
        active=False, statusChangedAt=datetime(2026, 11, 5, tzinfo=UTC)
    )
    response = TestClient(app).put(
        "/api/v1/admin/therapist-compensation/attendance/t1/2026-11-05",
        json={
            "present": True,
            "expectedVersion": 0,
        },
    )
    assert response.status_code == 422
    assert not database.data["therapist_attendance"]


def test_former_balances_include_old_pay_tips_and_legacy_payout_without_changing_history(database):
    database.data["therapists"]["t1"]["active"] = False
    database.data["therapists"]["t2"] = {
        "therapistId": "t2",
        "active": True,
        "branchId": "branch_001",
    }
    database.data["service_settlements"]["s1"] = {
        "branchId": "branch_001",
        "serviceDate": "2025-01-15",
        "allocations": [
            {"therapistId": "t1", "therapistPaySatang": 40000, "tipShareSatang": 5000},
            {"therapistId": "t2", "therapistPaySatang": 10000, "tipShareSatang": 0},
        ],
    }
    database.data["therapist_payouts"]["p1"] = {
        "branchId": "branch_001",
        "therapistId": "t1",
        "dateFrom": "2025-01-01",
        "dateTo": "2025-01-31",
        "amountSatang": 20000,
    }
    before = deepcopy(database.data)
    payload = compensation._former_outstanding_payload(database, "branch_001")
    row = payload["items"][0]
    assert row["therapistId"] == "t1"
    assert row["outstandingSatang"] == 25000
    assert row["dateFrom"] == "2025-01-01" and row["dateTo"] == "2025-01-31"
    assert database.data == before


def test_historical_report_keeps_former_staff_while_active_totals_exclude_them(database):
    database.data["therapists"]["t1"]["active"] = False
    payload = compensation._build_compensation_payload(
        therapists=list(database.data["therapists"].values()),
        guarantee_rates=[],
        attendances=[],
        adjustments=[
            {
                "documentId": "a1",
                "therapistId": "t1",
                "localDate": "2025-01-01",
                "amountSatang": 10000,
            }
        ],
        settlements=[],
        payouts=[],
        start=datetime(2025, 1, 1).date(),
        end=datetime(2026, 11, 5).date(),
        branch_id="branch_001",
    )
    assert payload["totals"]["outstandingSatang"] == 10000
    assert payload["activeTotals"]["outstandingSatang"] == 0
    assert payload["entries"][0]["therapistId"] == "t1"
    assert len(payload["summary"][0]["days"]) == 1
