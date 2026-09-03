from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.errors import InvalidStateTransition
from app.domains.campaigns import admin_service


class Snapshot:
    def __init__(self, document_id: str, value: dict[str, object] | None) -> None:
        self.id = document_id
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return dict(self.value) if self.value is not None else None


class Document:
    def __init__(self, database: "Database", collection: str, document_id: str) -> None:
        self.database = database
        self.collection = collection
        self.id = document_id

    def get(self, transaction=None):
        return Snapshot(self.id, self.database.data.get(self.collection, {}).get(self.id))

    def set(self, value: dict[str, object], merge: bool = False) -> None:
        store = self.database.data.setdefault(self.collection, {})
        store[self.id] = {**store.get(self.id, {}), **value} if merge else dict(value)


class Query:
    def __init__(self, database: "Database", collection: str) -> None:
        self.database = database
        self.collection = collection
        self.filters: list[tuple[str, object]] = []
        self.maximum: int | None = None

    def where(self, field: str, operator: str, value: object):
        assert operator == "=="
        self.filters.append((field, value))
        return self

    def limit(self, value: int):
        self.maximum = value
        return self

    def stream(self):
        values = [
            Snapshot(key, item)
            for key, item in self.database.data.get(self.collection, {}).items()
            if all(item.get(field) == value for field, value in self.filters)
        ]
        return values[: self.maximum]

    def document(self, document_id: str | None = None):
        if document_id is None:
            self.database.counter += 1
            document_id = f"generated-{self.database.counter:03d}"
        return Document(self.database, self.collection, document_id)


class Transaction:
    def set(self, ref: Document, value: dict[str, object], merge: bool = False) -> None:
        ref.set(value, merge)

    def update(self, ref: Document, value: dict[str, object]) -> None:
        ref.set(value, merge=True)


class Database:
    def __init__(self) -> None:
        self.counter = 0
        expires = datetime(2026, 9, 30, tzinfo=UTC)
        self.data: dict[str, dict[str, dict[str, object]]] = {
            "campaigns": {
                "welcome-50": {
                    "branchId": "branch_001",
                    "nameTh": "รับส่วนลด 50 บาท",
                    "status": "ACTIVE",
                    "version": 3,
                    "benefit": {"amountSatang": 5000, "currency": "THB"},
                }
            },
            "customers": {
                "customer-granted": {
                    "displayName": "ลูกค้า ก.",
                    "phoneMasked": "081-xxx-1111",
                    "friendStatus": "FOLLOWING",
                },
                "customer-denied": {
                    "displayName": "ลูกค้า ข.",
                    "phoneMasked": "082-xxx-2222",
                    "friendStatus": "FOLLOWING",
                },
            },
            "customer_private": {
                "customer-granted": {
                    "fullName": "Granted Customer",
                    "phoneE164": "+66811111111",
                    "birthDay": 1,
                    "birthMonth": 9,
                    "birthYear": 1992,
                },
                "customer-denied": {
                    "fullName": "Denied Customer",
                    "phoneE164": "+66822222222",
                    "birthDay": 2,
                    "birthMonth": 9,
                    "birthYear": 1988,
                },
            },
            "marketing_profiles": {
                "customer-granted": {
                    "birthdayMarketingStatus": "GRANTED",
                    "birthYear": 1992,
                },
                "customer-denied": {
                    "birthdayMarketingStatus": "DENIED",
                    "birthYear": 1988,
                },
            },
            "campaign_participations": {
                "p1": {
                    "campaignCode": "welcome-50",
                    "customerId": "customer-granted",
                    "claimedAt": datetime(2026, 8, 20, tzinfo=UTC),
                },
                "p2": {
                    "campaignCode": "welcome-50",
                    "customerId": "customer-denied",
                    "claimedAt": datetime(2026, 8, 20, tzinfo=UTC),
                },
            },
            "coupons": {
                "coupon-001": {
                    "code": "W50-TEST",
                    "campaignCode": "welcome-50",
                    "customerId": "customer-granted",
                    "status": "ISSUED",
                    "amountSatang": 5000,
                    "expiresAt": expires,
                    "version": 1,
                }
            },
        }

    def collection(self, name: str):
        return Query(self, name)

    def transaction(self):
        return Transaction()


@pytest.fixture
def database(monkeypatch):
    value = Database()
    monkeypatch.setattr(admin_service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        admin_service,
        "get_settings",
        lambda: type("Settings", (), {"default_branch_id": "branch_001"})(),
    )
    return value


def test_staff_has_masked_crm_access_but_cannot_reveal_pii(database) -> None:
    actor = {"uid": "staff-001", "role": "STAFF", "branchIds": ["branch_001"]}
    rows = admin_service.list_campaign_customers(
        database, actor, "branch_001", None, None, None, 100
    )

    assert rows[0]["phoneMasked"] == "081-xxx-1111"
    assert rows[0]["birthYear"] == 1992
    assert rows[1]["birthYear"] is None
    assert "phoneE164" not in rows[0]
    with pytest.raises(HTTPException) as error:
        admin_service.reveal_customer_pii(
            database, actor, "customer-granted", "branch_001", "support"
        )
    assert error.value.status_code == 403


def test_crm_export_contains_only_granted_marketing_customers(database) -> None:
    actor = {"uid": "admin-001", "role": "ADMIN", "branchIds": ["branch_001"]}
    content = admin_service.export_campaign_customers_csv(
        database, actor, "branch_001", "welcome-50"
    )

    assert "Granted Customer" in content
    assert "Denied Customer" not in content
    assert "birthYear,birthYearBuddhist" in content
    assert "1992,2535" in content
    audit = next(iter(database.data["audit_events"].values()))
    assert audit["eventType"] == "CRM_CUSTOMERS_EXPORTED"
    assert audit["consentFilter"] == "BIRTHDAY_MARKETING=GRANTED"


def test_coupon_redeem_is_single_use_and_audited(database) -> None:
    actor = {"uid": "staff-001", "role": "STAFF", "branchIds": ["branch_001"]}
    now = datetime(2026, 8, 20, tzinfo=UTC)
    first = admin_service.transition_coupon(
        database,
        actor,
        "coupon-001",
        "REDEEMED",
        "branch_001",
        1,
        "command-001",
        now=now,
    )

    assert first["status"] == "REDEEMED"
    assert database.data["coupons"]["coupon-001"]["version"] == 2
    with pytest.raises(InvalidStateTransition):
        admin_service.transition_coupon(
            database,
            actor,
            "coupon-001",
            "REDEEMED",
            "branch_001",
            2,
            "command-002",
            now=now + timedelta(seconds=1),
        )
    assert any(
        event["eventType"] == "COUPON_REDEEMED" for event in database.data["audit_events"].values()
    )
