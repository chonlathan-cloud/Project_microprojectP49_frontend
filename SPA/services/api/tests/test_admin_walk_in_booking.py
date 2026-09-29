from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import bookings as booking_routes
from app.core.auth import require_admin_user
from app.core.errors import AdvanceWindowViolation, ValidationDomainError
from app.core.settings import Settings
from app.domains.bookings import service as booking_service
from app.infrastructure.firestore import get_firestore_client
from app.infrastructure.firestore_payments import _payment_id
from app.main import app

client = TestClient(app)


class Snapshot:
    def __init__(
        self,
        document_id: str,
        data: dict[str, object] | None,
        reference: Document | None = None,
    ) -> None:
        self.id = document_id
        self._data = data
        self.exists = data is not None
        self.reference = reference

    def to_dict(self) -> dict[str, object]:
        return dict(self._data or {})


class Document:
    def __init__(self, database: WalkInFirestore, collection: str, document_id: str) -> None:
        self.database = database
        self.collection_name = collection
        self.id = document_id

    def get(self, transaction: object | None = None) -> Snapshot:
        del transaction
        return Snapshot(
            self.id,
            self.database.documents.get((self.collection_name, self.id)),
            self,
        )


class Query:
    def __init__(self, database: WalkInFirestore, collection: str) -> None:
        self.database = database
        self.collection_name = collection
        self.filters: list[tuple[str, str, object]] = []

    def where(self, field: str, operator: str, value: object) -> Query:
        self.filters.append((field, operator, value))
        return self

    def limit(self, _value: int) -> Query:
        return self

    def stream(self, transaction: object | None = None) -> list[Snapshot]:
        del transaction
        snapshots: list[Snapshot] = []
        for (collection, document_id), data in self.database.documents.items():
            if collection != self.collection_name:
                continue
            if any(
                operator != "==" or data.get(field) != value
                for field, operator, value in self.filters
            ):
                continue
            reference = Document(self.database, collection, document_id)
            snapshots.append(Snapshot(document_id, data, reference))
        return snapshots

    def document(self, document_id: str | None = None) -> Document:
        if document_id is None:
            self.database.sequence += 1
            document_id = f"auto-{self.database.sequence}"
        return Document(self.database, self.collection_name, document_id)


class Transaction:
    def __init__(self, database: WalkInFirestore) -> None:
        self.database = database

    def set(self, reference: Document, value: dict[str, object], merge: bool = False) -> None:
        current = self.database.documents.get((reference.collection_name, reference.id), {})
        stored = {**current, **value} if merge else dict(value)
        self.database.documents[(reference.collection_name, reference.id)] = stored

    def update(self, reference: Document, value: dict[str, object]) -> None:
        current = self.database.documents.get((reference.collection_name, reference.id), {})
        self.database.documents[(reference.collection_name, reference.id)] = {
            **current,
            **value,
        }


class WalkInFirestore:
    def __init__(self) -> None:
        self.sequence = 0
        self.documents: dict[tuple[str, str], dict[str, object]] = {
            (
                "branches",
                "branch_001",
            ): {
                "activeCapacityUnits": 4,
                "operatingHours": {
                    "0": {"open": "00:00", "close": "23:59"},
                },
            }
        }

    def collection(self, name: str) -> Query:
        return Query(self, name)

    def transaction(self) -> Transaction:
        return Transaction(self)


def _override_dependencies(database: object, *, role: str = "STAFF") -> tuple[object, object]:
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "staff-001",
        "role": role,
    }
    app.dependency_overrides[get_firestore_client] = lambda: database
    return previous_auth, previous_firestore


def _restore_dependencies(previous_auth: object, previous_firestore: object) -> None:
    if previous_auth is None:
        app.dependency_overrides.pop(require_admin_user, None)
    else:
        app.dependency_overrides[require_admin_user] = previous_auth
    if previous_firestore is None:
        app.dependency_overrides.pop(get_firestore_client, None)
    else:
        app.dependency_overrides[get_firestore_client] = previous_firestore


def test_admin_walk_in_endpoint_requires_authentication() -> None:
    response = client.post(
        "/api/v1/admin/bookings",
        headers={"Idempotency-Key": "walk-in-001"},
        json={
            "bookingMode": "WALK_IN",
            "date": "2026-08-31",
            "time": "14:00",
            "phone": None,
            "bookingPrivacyAcknowledged": True,
            "consentCaptureMethod": "VERBAL",
            "participants": [
                {
                    "nickname": "Som",
                    "serviceVariantId": "traditional-thai-60",
                    "hasHealthInformation": False,
                    "healthDetails": None,
                    "healthConsent": True,
                }
            ],
        },
    )
    assert response.status_code == 401


def test_admin_walk_in_endpoint_supplies_trusted_actor_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_booking(_client: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"bookingId": "BK-20260831-001", "status": "CONFIRMED"}

    monkeypatch.setattr(booking_routes, "create_booking", fake_create_booking)
    previous_auth, previous_firestore = _override_dependencies(WalkInFirestore())
    try:
        response = client.post(
            "/api/v1/admin/bookings",
            headers={"Idempotency-Key": "walk-in-001"},
            json={
                "bookingMode": "WALK_IN",
                "date": "2026-08-31",
                "time": "14:00",
                "phone": None,
                "bookingPrivacyAcknowledged": True,
                "consentCaptureMethod": "PAPER",
                "participants": [
                    {
                        "nickname": "Som",
                        "serviceVariantId": "traditional-thai-60",
                        "hasHealthInformation": False,
                        "healthDetails": None,
                        "healthConsent": True,
                    }
                ],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201, response.text
    assert captured["source"] == "ADMIN_WEB"
    assert captured["initial_status"] == "CONFIRMED"
    assert captured["admin_booking_mode"] == "WALK_IN"
    assert captured["actor_id"] == "staff-001"
    assert captured["phone"] is None
    assert captured["consent_capture_method"] == "PAPER"


def test_staff_cannot_apply_booking_discount() -> None:
    previous_auth, previous_firestore = _override_dependencies(WalkInFirestore())
    try:
        response = client.post(
            "/api/v1/admin/bookings",
            headers={"Idempotency-Key": "discount-staff-001"},
            json={
                "bookingMode": "STAFF_ASSISTED",
                "date": "2026-09-05",
                "time": "14:00",
                "phone": None,
                "bookingPrivacyAcknowledged": True,
                "consentCaptureMethod": "VERBAL",
                "discountAmountSatang": 5000,
                "discountReason": "คูปองสมัครครั้งแรก",
                "participants": [
                    {
                        "nickname": "Som",
                        "serviceVariantId": "traditional-thai-60",
                        "hasHealthInformation": False,
                        "healthDetails": None,
                        "healthConsent": True,
                    }
                ],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_admin_discount_is_forwarded_with_trusted_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_booking(_client: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"bookingId": "BK-20260905-001", "status": "CONFIRMED"}

    monkeypatch.setattr(booking_routes, "create_booking", fake_create_booking)
    previous_auth, previous_firestore = _override_dependencies(WalkInFirestore(), role="ADMIN")
    try:
        response = client.post(
            "/api/v1/admin/bookings",
            headers={"Idempotency-Key": "discount-admin-001"},
            json={
                "bookingMode": "STAFF_ASSISTED",
                "date": "2026-09-05",
                "time": "14:00",
                "phone": None,
                "bookingPrivacyAcknowledged": True,
                "consentCaptureMethod": "VERBAL",
                "discountAmountSatang": 5000,
                "discountReason": "  คูปองสมัครครั้งแรก  ",
                "participants": [
                    {
                        "nickname": "Som",
                        "serviceVariantId": "traditional-thai-60",
                        "hasHealthInformation": False,
                        "healthDetails": None,
                        "healthConsent": True,
                    }
                ],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201, response.text
    assert captured["actor_role"] == "ADMIN"
    assert captured["discount_amount_satang"] == 5000
    assert captured["discount_reason"] == "  คูปองสมัครครั้งแรก  "


def test_walk_in_window_rejects_other_dates_and_past_buckets() -> None:
    now = datetime(2026, 8, 31, 7, 7, tzinfo=UTC)  # 14:07 in Bangkok
    booking_service._validate_walk_in_window(
        datetime.fromisoformat("2026-08-31T14:00:00+07:00"),
        now=now,
    )
    with pytest.raises(AdvanceWindowViolation, match="past"):
        booking_service._validate_walk_in_window(
            datetime.fromisoformat("2026-08-31T13:45:00+07:00"),
            now=now,
        )
    with pytest.raises(AdvanceWindowViolation, match="current"):
        booking_service._validate_walk_in_window(
            datetime.fromisoformat("2026-09-01T14:00:00+07:00"),
            now=now,
        )


def test_walk_in_transaction_uses_no_fake_phone_and_commits_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(booking_service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(booking_service, "_validate_walk_in_window", lambda *args, **kwargs: None)

    result = booking_service.create_booking(
        database,  # type: ignore[arg-type]
        branch_id="branch_001",
        date="2026-08-31",
        time="14:00",
        phone=None,
        participants=[
            {
                "nickname": "Som",
                "serviceVariantId": "traditional-thai-60",
                "hasHealthInformation": False,
                "healthDetails": None,
                "healthConsent": True,
            }
        ],
        idempotency_key="walk-in-transaction-001",
        source="ADMIN_WEB",
        initial_status="CONFIRMED",
        actor_id="staff-001",
        admin_booking_mode="WALK_IN",
        consent_capture_method="VERBAL",
        booking_privacy_acknowledged=True,
    )

    assert result["status"] == "CONFIRMED"
    assert "statusToken" not in result
    bookings = [
        value for (collection, _), value in database.documents.items() if collection == "bookings"
    ]
    assert len(bookings) == 1
    booking = bookings[0]
    assert booking["source"] == "ADMIN_WEB"
    assert booking["status"] == "CONFIRMED"
    assert booking["contact"] == {"mode": "NONE"}
    assert booking["confirmedBy"] == "staff-001"
    assert "statusTokenHash" not in booking

    consents = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "consent_evidence"
    ]
    assert {item["purpose"] for item in consents} == {
        "HEALTH_DATA_EXPLICIT",
        "BOOKING_PRIVACY_ACK",
    }
    assert all(item["captureMethod"] == "VERBAL" for item in consents)
    assert all(item["capturedByActorId"] == "staff-001" for item in consents)

    audits = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
    ]
    assert audits[-1]["actorType"] == "ADMIN_USER"
    assert audits[-1]["toStatus"] == "CONFIRMED"


def test_multi_service_transaction_writes_shared_package_timeline_and_exact_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(booking_service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(booking_service, "_validate_walk_in_window", lambda *args, **kwargs: None)

    result = booking_service.create_booking(
        database,  # type: ignore[arg-type]
        branch_id="branch_001",
        date="2026-08-31",
        time="14:00",
        phone=None,
        participants=[
            {
                "nickname": "Som",
                "services": [
                    {"serviceVariantId": "couple-relaxation-90"},
                    {"serviceVariantId": "traditional-thai-60"},
                ],
                "hasHealthInformation": False,
                "healthDetails": None,
                "healthConsent": True,
            },
            {
                "nickname": "May",
                "services": [
                    {"serviceVariantId": "couple-relaxation-90"},
                    {"serviceVariantId": "hot-compress-neck-shoulder-back-20"},
                ],
                "hasHealthInformation": False,
                "healthDetails": None,
                "healthConsent": True,
            },
        ],
        idempotency_key="multi-service-transaction-001",
        source="ADMIN_WEB",
        initial_status="CONFIRMED",
        actor_id="staff-001",
        admin_booking_mode="WALK_IN",
        consent_capture_method="VERBAL",
        booking_privacy_acknowledged=True,
    )

    booking = next(
        value for (collection, _), value in database.documents.items() if collection == "bookings"
    )
    lines = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "booking_line_items"
    ]
    lines.sort(key=lambda item: int(item["sequence"]))
    reservation = booking["capacityReservation"]
    assert isinstance(reservation, dict)

    assert result["subtotalAmountSatang"] == sum(int(item["lineTotalSatang"]) for item in lines)
    assert len(lines) == 3
    assert len(lines[0]["participantIds"]) == 2
    assert lines[0]["lineTotalSatang"] == 119_000
    assert [line["participantSequence"] for line in lines] == [1, 1, 2]
    assert int((booking["endAt"] - booking["startAt"]).total_seconds() // 60) == 150
    assert [item["units"] for item in reservation["bucketUnits"]] == [
        2,
        2,
        2,
        2,
        2,
        2,
        2,
        2,
        1,
        1,
    ]


def test_admin_discount_persists_subtotal_net_amount_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(booking_service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        booking_service, "_validate_staff_assisted_window", lambda *args, **kwargs: None
    )

    result = booking_service.create_booking(
        database,  # type: ignore[arg-type]
        branch_id="branch_001",
        date="2026-09-05",
        time="14:00",
        phone=None,
        participants=[
            {
                "nickname": "Som",
                "serviceVariantId": "traditional-thai-60",
                "hasHealthInformation": False,
                "healthDetails": None,
                "healthConsent": True,
            }
        ],
        idempotency_key="discount-transaction-001",
        source="ADMIN_WEB",
        initial_status="CONFIRMED",
        actor_id="admin-001",
        actor_role="ADMIN",
        admin_booking_mode="STAFF_ASSISTED",
        consent_capture_method="VERBAL",
        booking_privacy_acknowledged=True,
        discount_amount_satang=2_000,
        discount_reason="  คูปองสมัครครั้งแรก  ",
    )

    assert result["subtotalAmountSatang"] == 30_000
    assert result["discountAmountSatang"] == 2_000
    assert result["estimatedAmountSatang"] == 28_000
    booking = next(
        value for (collection, _), value in database.documents.items() if collection == "bookings"
    )
    assert booking["subtotalAmountSatang"] == 30_000
    assert booking["discountAmountSatang"] == 2_000
    assert booking["estimatedAmountSatang"] == 28_000
    assert booking["discountReason"] == "คูปองสมัครครั้งแรก"
    assert booking["discountAppliedBy"] == "admin-001"
    discount_audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events" and value.get("eventType") == "BOOKING_DISCOUNT_APPLIED"
    )
    assert discount_audit["finalAmountSatang"] == 28_000
    assert discount_audit["actorRole"] == "ADMIN"


@pytest.mark.parametrize(
    ("booking_mode", "discount_amount_satang", "discount_reason", "message"),
    [
        ("STAFF_ASSISTED", 50, "Coupon", "whole-baht"),
        ("STAFF_ASSISTED", 2_000, None, "reason is required"),
    ],
)
def test_admin_discount_rejects_invalid_financial_input(
    monkeypatch: pytest.MonkeyPatch,
    booking_mode: str,
    discount_amount_satang: int,
    discount_reason: str | None,
    message: str,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(
        booking_service, "_validate_staff_assisted_window", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        booking_service, "_validate_historical_record_window", lambda *args, **kwargs: None
    )

    with pytest.raises(ValidationDomainError, match=message):
        booking_service.create_booking(
            database,  # type: ignore[arg-type]
            branch_id="branch_001",
            date="2026-08-20",
            time="14:00",
            phone=None,
            participants=[
                {
                    "nickname": "Som",
                    "serviceVariantId": "traditional-thai-60",
                    "hasHealthInformation": False,
                    "healthDetails": None,
                    "healthConsent": True,
                }
            ],
            idempotency_key=f"discount-invalid-{discount_amount_satang}-{booking_mode}",
            source="ADMIN_WEB",
            initial_status="RECORDED" if booking_mode == "HISTORICAL_RECORD" else "CONFIRMED",
            actor_id="admin-001",
            actor_role="ADMIN",
            admin_booking_mode=booking_mode,
            consent_capture_method="VERBAL",
            booking_privacy_acknowledged=True,
            discount_amount_satang=discount_amount_satang,
            discount_reason=discount_reason,
        )


@pytest.mark.parametrize(
    ("booking_mode", "tip_amount_satang", "message"),
    [
        ("STAFF_ASSISTED", 2_000, "only be recorded for historical"),
        ("HISTORICAL_RECORD", 50, "whole-baht"),
    ],
)
def test_admin_tip_rejects_non_historical_or_fractional_amount(
    monkeypatch: pytest.MonkeyPatch,
    booking_mode: str,
    tip_amount_satang: int,
    message: str,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(
        booking_service, "_validate_staff_assisted_window", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        booking_service, "_validate_historical_record_window", lambda *args, **kwargs: None
    )

    with pytest.raises(ValidationDomainError, match=message):
        booking_service.create_booking(
            database,  # type: ignore[arg-type]
            branch_id="branch_001",
            date="2026-08-20",
            time="14:00",
            phone=None,
            participants=[
                {
                    "nickname": "Som",
                    "serviceVariantId": "traditional-thai-60",
                    "hasHealthInformation": False,
                    "healthDetails": None,
                    "healthConsent": True,
                }
            ],
            idempotency_key=f"tip-invalid-{tip_amount_satang}-{booking_mode}",
            source="ADMIN_WEB",
            initial_status=("RECORDED" if booking_mode == "HISTORICAL_RECORD" else "CONFIRMED"),
            actor_id="staff-001",
            actor_role="ADMIN",
            admin_booking_mode=booking_mode,
            consent_capture_method="VERBAL",
            booking_privacy_acknowledged=True,
            tip_amount_satang=tip_amount_satang,
            historical_payment_source=(
                "CASH" if booking_mode == "HISTORICAL_RECORD" else None
            ),
            historical_paid_at=(
                datetime.fromisoformat("2026-08-20T15:00:00+07:00")
                if booking_mode == "HISTORICAL_RECORD"
                else None
            ),
        )


def test_staff_assisted_and_historical_windows_are_mutually_exclusive() -> None:
    now = datetime(2026, 9, 1, 7, 7, tzinfo=UTC)  # 14:07 in Bangkok
    future = datetime.fromisoformat("2026-09-05T14:00:00+07:00")
    past = datetime.fromisoformat("2026-08-31T14:00:00+07:00")

    booking_service._validate_staff_assisted_window(future, now=now)
    booking_service._validate_historical_record_window(past, now=now)
    with pytest.raises(AdvanceWindowViolation, match="HISTORICAL_RECORD"):
        booking_service._validate_staff_assisted_window(past, now=now)
    with pytest.raises(AdvanceWindowViolation, match="past"):
        booking_service._validate_historical_record_window(future, now=now)


def test_historical_record_is_financial_history_and_skips_capacity_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(booking_service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        booking_service,
        "_validate_historical_record_window",
        lambda *args, **kwargs: None,
    )

    result = booking_service.create_booking(
        database,  # type: ignore[arg-type]
        branch_id="branch_001",
        date="2026-08-20",
        time="14:00",
        phone=None,
        participants=[
            {
                "nickname": "Som",
                "serviceVariantId": "traditional-thai-60",
                "hasHealthInformation": False,
                "healthDetails": None,
                "healthConsent": True,
            }
        ],
        idempotency_key="historical-record-001",
        source="ADMIN_WEB",
        initial_status="RECORDED",
        actor_id="admin-001",
        actor_role="ADMIN",
        admin_booking_mode="HISTORICAL_RECORD",
        consent_capture_method="VERBAL",
        booking_privacy_acknowledged=True,
        tip_amount_satang=5_000,
        historical_payment_source="CASH",
        historical_paid_at=datetime.fromisoformat("2026-08-20T15:00:00+07:00"),
    )

    assert result["status"] == "RECORDED"
    assert result["subtotalAmountSatang"] == 30_000
    assert result["discountAmountSatang"] == 0
    assert result["estimatedAmountSatang"] == 30_000
    assert result["tipAmountSatang"] == 5_000
    assert result["grossAmountSatang"] == 35_000
    booking = next(
        value for (collection, _), value in database.documents.items() if collection == "bookings"
    )
    assert booking["customerListBucket"] == "HISTORY"
    assert booking["financiallyExcluded"] is False
    assert booking["historicalFinancialRecord"] is True
    assert booking["subtotalAmountSatang"] == 30_000
    assert booking["estimatedAmountSatang"] == 30_000
    assert booking["tipAmountSatang"] == 5_000
    assert booking["grossAmountSatang"] == 35_000
    assert booking["paymentStatus"] == "PAID"
    assert booking["paidAmountSatang"] == 35_000
    assert booking["amountDueSatang"] == 0
    assert booking["capacityReleased"] is True
    assert "capacityReservation" not in booking
    assert booking["recordedBy"] == "admin-001"
    assert not any(collection == "capacity_buckets" for collection, _ in database.documents)
    assert not any(collection == "notification_outbox" for collection, _ in database.documents)
    payment = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "payments"
    )
    assert payment["status"] == "PAID"
    assert payment["paymentMethod"] == "CASH"
    assert payment["grossAmountSatang"] == 35_000
    accounting_export = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "accounting_exports"
    )
    assert accounting_export["status"] == "READY"
    assert accounting_export["paymentSource"] == "CASH"
    line_item = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "booking_line_items"
    )
    assert line_item["lineTotalSatang"] == 30_000
    assert line_item["financiallyExcluded"] is False
    audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and value.get("eventType") == "BOOKING_HISTORY_RECORDED"
    )
    assert audit["eventType"] == "BOOKING_HISTORY_RECORDED"
    assert audit["subtotalAmountSatang"] == 30_000
    assert audit["discountAmountSatang"] == 0
    assert audit["estimatedAmountSatang"] == 30_000
    assert audit["tipAmountSatang"] == 5_000
    assert audit["grossAmountSatang"] == 35_000
    payment_audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and value.get("eventType") == "HISTORICAL_PAYMENT_RECORDED"
    )
    assert payment_audit["paymentSource"] == "CASH"


def test_historical_record_accepts_admin_discount_and_preserves_net_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    monkeypatch.setattr(booking_service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        booking_service,
        "_validate_historical_record_window",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        booking_service,
        "get_settings",
        lambda: Settings(
            accounting_bank_accounts_json=(
                '[{"key":"kbank-6073-a","bankAccountId":"462850",'
                '"transferBankAccountId":"2",'
                '"labelTh":"KBank ••••6073 · Company (บัญชี A)",'
                '"labelEn":"KBank ••••6073 · Company (Account A)"}]'
            )
        ),
    )

    result = booking_service.create_booking(
        database,  # type: ignore[arg-type]
        branch_id="branch_001",
        date="2026-08-20",
        time="14:00",
        phone=None,
        participants=[
            {
                "nickname": "Som",
                "serviceVariantId": "traditional-thai-60",
                "hasHealthInformation": False,
                "healthDetails": None,
                "healthConsent": True,
            }
        ],
        idempotency_key="historical-discount-001",
        source="ADMIN_WEB",
        initial_status="RECORDED",
        actor_id="admin-001",
        actor_role="ADMIN",
        admin_booking_mode="HISTORICAL_RECORD",
        consent_capture_method="PAPER",
        booking_privacy_acknowledged=True,
        discount_amount_satang=2_000,
        discount_reason="คูปองสมัครครั้งแรก",
        historical_payment_source="BANK_TRANSFER",
        historical_paid_at=datetime.fromisoformat("2026-08-20T15:00:00+07:00"),
        historical_bank_account_key="kbank-6073-a",
    )

    assert result["subtotalAmountSatang"] == 30_000
    assert result["discountAmountSatang"] == 2_000
    assert result["estimatedAmountSatang"] == 28_000
    booking = next(
        value for (collection, _), value in database.documents.items() if collection == "bookings"
    )
    assert booking["discountReason"] == "คูปองสมัครครั้งแรก"
    assert booking["estimatedAmountSatang"] == 28_000
    assert booking["financiallyExcluded"] is False
    discount_audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events" and value.get("eventType") == "BOOKING_DISCOUNT_APPLIED"
    )
    assert discount_audit["finalAmountSatang"] == 28_000


def test_historical_record_can_be_cancelled_without_capacity_or_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    database.documents[("bookings", "booking-history-001")] = {
        "publicBookingId": "BK-20260820-001",
        "status": "RECORDED",
        "version": 1,
        "customerListBucket": "HISTORY",
        "adminEntryMode": "HISTORICAL_RECORD",
        "historicalFinancialRecord": True,
        "financiallyExcluded": False,
        "capacityReleased": True,
        "subtotalAmountSatang": 30_000,
        "discountAmountSatang": 2_000,
        "estimatedAmountSatang": 28_000,
        "tipAmountSatang": 5_000,
        "grossAmountSatang": 33_000,
    }
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database)
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260820-001:cancel",
            json={
                "reason": "บันทึกผิดรายการ",
                "expectedVersion": 1,
                "commandId": "cancel-history-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    booking = database.documents[("bookings", "booking-history-001")]
    assert booking["status"] == "CANCELLED"
    assert booking["financiallyExcluded"] is True
    assert booking["capacityReleased"] is True
    assert booking["subtotalAmountSatang"] == 30_000
    assert booking["discountAmountSatang"] == 2_000
    assert booking["estimatedAmountSatang"] == 28_000
    assert booking["tipAmountSatang"] == 5_000
    assert booking["grossAmountSatang"] == 33_000
    assert booking["cancellation"]["reason"] == "บันทึกผิดรายการ"  # type: ignore[index]
    assert not any(collection == "capacity_buckets" for collection, _ in database.documents)
    assert not any(collection == "notification_outbox" for collection, _ in database.documents)
    status_audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events" and value.get("eventType") == "BOOKING_STATUS_CHANGED"
    )
    assert status_audit["fromStatus"] == "RECORDED"
    assert status_audit["toStatus"] == "CANCELLED"
    assert status_audit["reason"] == "บันทึกผิดรายการ"


def _seed_paid_historical_record(
    database: WalkInFirestore,
    *,
    export_status: str = "READY",
    payment_method: str = "BANK_TRANSFER",
    cash_settlement_status: str = "NOT_APPLICABLE",
    with_settlement: bool = False,
) -> tuple[str, str]:
    booking_doc_id = "booking-history-paid-001"
    booking_public_id = "BK-20260922-F8DA4A"
    payment_id = _payment_id(booking_doc_id)
    database.documents[("bookings", booking_doc_id)] = {
        "publicBookingId": booking_public_id,
        "branchId": "branch_001",
        "localDate": "2026-09-22",
        "status": "RECORDED",
        "version": 1,
        "customerListBucket": "HISTORY",
        "adminEntryMode": "HISTORICAL_RECORD",
        "historicalFinancialRecord": True,
        "financiallyExcluded": False,
        "capacityReleased": True,
        "paymentStatus": "PAID",
        "paidAmountSatang": 30_000,
        "amountDueSatang": 0,
        "estimatedAmountSatang": 30_000,
        "tipAmountSatang": 0,
        "grossAmountSatang": 30_000,
    }
    database.documents[("payments", payment_id)] = {
        "bookingDocId": booking_doc_id,
        "bookingPublicId": booking_public_id,
        "branchId": "branch_001",
        "status": "PAID",
        "paymentMethod": payment_method,
        "cashSettlementStatus": cash_settlement_status,
        "grossAmountSatang": 30_000,
        "paidAmountSatang": 30_000,
        "version": 2,
    }
    database.documents[("accounting_exports", "fa-history-paid-001")] = {
        "bookingDocId": booking_doc_id,
        "bookingPublicId": booking_public_id,
        "paymentId": payment_id,
        "branchId": "branch_001",
        "status": export_status,
        "attemptCount": 0,
        "grossAmountSatang": 30_000,
    }
    if with_settlement:
        database.documents[("service_settlements", booking_doc_id)] = {
            "bookingDocId": booking_doc_id,
            "bookingPublicId": booking_public_id,
            "branchId": "branch_001",
            "serviceDate": "2026-09-22",
            "state": "ALLOCATED",
            "version": 1,
            "allocations": [
                {
                    "therapistId": "therapist-001",
                    "therapistPaySatang": 12_000,
                    "tipShareSatang": 0,
                }
            ],
        }
    return booking_doc_id, payment_id


def test_paid_historical_record_uses_typed_correction_error_on_ordinary_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    _seed_paid_historical_record(database)
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="ADMIN")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:cancel",
            json={
                "reason": "กรอกข้อมูลผิด",
                "expectedVersion": 1,
                "commandId": "ordinary-cancel-paid-history-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 409
    assert response.json()["code"] == "HISTORICAL_CORRECTION_REQUIRED"


def test_admin_can_void_ready_paid_historical_record_atomically_and_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    booking_doc_id, payment_id = _seed_paid_historical_record(
        database, with_settlement=True
    )
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    from app.infrastructure import firestore_historical_corrections as correction_store

    monkeypatch.setattr(correction_store.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="ADMIN")
    request = {
        "reason": "กรอกข้อมูลผิด",
        "expectedVersion": 1,
        "commandId": "void-paid-history-001",
    }
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json=request,
        )
        replay = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json=request,
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    assert response.json() == {
        "bookingId": "BK-20260922-F8DA4A",
        "status": "CANCELLED",
        "version": 2,
        "paymentStatus": "VOIDED",
        "exportStatus": "CANCELLED",
        "financiallyExcluded": True,
    }
    booking = database.documents[("bookings", booking_doc_id)]
    assert booking["status"] == "CANCELLED"
    assert booking["financiallyExcluded"] is True
    assert booking["paymentStatus"] == "VOIDED"
    assert booking["cancellation"]["kind"] == "HISTORICAL_FINANCIAL_VOID"  # type: ignore[index]
    payment = database.documents[("payments", payment_id)]
    assert payment["status"] == "VOIDED"
    assert payment["paidAmountSatang"] == 0
    assert payment["voidReason"] == "กรอกข้อมูลผิด"
    export = database.documents[("accounting_exports", "fa-history-paid-001")]
    assert export["status"] == "CANCELLED"
    settlement = database.documents[("service_settlements", booking_doc_id)]
    assert settlement["state"] == "VOIDED"
    audits = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and value.get("eventType") == "HISTORICAL_FINANCIAL_RECORD_VOIDED"
    ]
    assert len(audits) == 1
    assert audits[0]["reason"] == "กรอกข้อมูลผิด"


@pytest.mark.parametrize(
    ("export_status", "reason_code"),
    [
        ("ENQUEUED", "ACCOUNTING_EXPORT_IN_FLIGHT"),
        ("PROCESSING", "ACCOUNTING_EXPORT_IN_FLIGHT"),
        ("SYNCED", "ACCOUNTING_EXPORT_SYNCED"),
        ("RETRYABLE", "ACCOUNTING_CORRECTION_REQUIRED"),
    ],
)
def test_historical_void_rejects_export_that_is_not_pristine_ready(
    monkeypatch: pytest.MonkeyPatch,
    export_status: str,
    reason_code: str,
) -> None:
    database = WalkInFirestore()
    booking_doc_id, _ = _seed_paid_historical_record(
        database, export_status=export_status
    )
    from app.infrastructure import firestore_historical_corrections as correction_store

    monkeypatch.setattr(correction_store.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="ADMIN")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json={
                "reason": "กรอกข้อมูลผิด",
                "expectedVersion": 1,
                "commandId": f"void-{export_status.lower()}-history-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 409
    assert response.json()["code"] == "HISTORICAL_CORRECTION_REQUIRED"
    assert response.json()["detail"] == reason_code
    assert database.documents[("bookings", booking_doc_id)]["status"] == "RECORDED"
    assert database.documents[("accounting_exports", "fa-history-paid-001")][
        "status"
    ] == export_status


@pytest.mark.parametrize(
    ("export_patch", "expected_detail"),
    [
        ({"attemptCount": 1}, "ACCOUNTING_EXPORT_ATTEMPTED"),
        ({"flowAccountDocumentId": "flow-doc-001"}, "ACCOUNTING_EXPORT_ATTEMPTED"),
    ],
)
def test_historical_void_rejects_ready_export_with_accounting_evidence(
    monkeypatch: pytest.MonkeyPatch,
    export_patch: dict[str, object],
    expected_detail: str,
) -> None:
    database = WalkInFirestore()
    booking_doc_id, _ = _seed_paid_historical_record(database)
    database.documents[("accounting_exports", "fa-history-paid-001")].update(
        export_patch
    )
    from app.infrastructure import firestore_historical_corrections as correction_store

    monkeypatch.setattr(correction_store.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="ADMIN")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json={
                "reason": "กรอกข้อมูลผิด",
                "expectedVersion": 1,
                "commandId": "void-attempted-history-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail
    assert database.documents[("bookings", booking_doc_id)]["status"] == "RECORDED"


def test_historical_void_rejects_active_cash_deposit_and_paid_compensation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure import firestore_historical_corrections as correction_store

    monkeypatch.setattr(correction_store.firestore, "transactional", lambda function: function)

    cash_database = WalkInFirestore()
    _, cash_payment_id = _seed_paid_historical_record(
        cash_database,
        payment_method="CASH",
        cash_settlement_status="DEPOSIT_PENDING",
    )
    cash_database.documents[("cash_deposit_allocation_guards", cash_payment_id)] = {
        "active": True,
        "depositId": "dep-001",
    }
    previous_auth, previous_firestore = _override_dependencies(cash_database, role="ADMIN")
    try:
        cash_response = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json={
                "reason": "กรอกข้อมูลผิด",
                "expectedVersion": 1,
                "commandId": "void-cash-history-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert cash_response.status_code == 409
    assert cash_response.json()["detail"] == "CASH_SETTLEMENT_IN_PROGRESS"

    payout_database = WalkInFirestore()
    _seed_paid_historical_record(payout_database, with_settlement=True)
    payout_database.documents[("therapist_payouts", "payout-001")] = {
        "branchId": "branch_001",
        "therapistId": "therapist-001",
        "dailyAllocations": [
            {"localDate": "2026-09-22", "amountSatang": 12_000}
        ],
    }
    previous_auth, previous_firestore = _override_dependencies(payout_database, role="ADMIN")
    try:
        payout_response = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json={
                "reason": "กรอกข้อมูลผิด",
                "expectedVersion": 1,
                "commandId": "void-payout-history-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert payout_response.status_code == 409
    assert payout_response.json()["detail"] == "THERAPIST_COMPENSATION_PAID"


def test_historical_void_is_admin_only_and_detail_exposes_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    _seed_paid_historical_record(database)
    previous_auth, previous_firestore = _override_dependencies(database, role="STAFF")
    try:
        forbidden = client.post(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A:void-historical",
            json={
                "reason": "กรอกข้อมูลผิด",
                "expectedVersion": 1,
                "commandId": "staff-void-history-001",
            },
        )
        detail = client.get(
            "/api/v1/admin/bookings/BK-20260922-F8DA4A"
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"
    assert detail.status_code == 200, detail.text
    assert detail.json()["historicalVoid"] == {
        "eligible": True,
        "reasonCode": None,
        "paymentStatus": "PAID",
        "exportStatus": "READY",
        "settlementState": None,
    }


def test_admin_start_service_applies_discount_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    database.documents[("bookings", "booking-active-001")] = {
        "publicBookingId": "BK-20260902-001",
        "branchId": "branch_001",
        "status": "CONFIRMED",
        "version": 3,
        "assignmentState": "ASSIGNED",
        "customerListBucket": "UPCOMING",
        "subtotalAmountSatang": 60_000,
        "discountAmountSatang": 0,
        "estimatedAmountSatang": 60_000,
        "tipAmountSatang": 0,
        "grossAmountSatang": 60_000,
        "capacityReleased": False,
    }
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="ADMIN")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260902-001:start",
            json={
                "expectedVersion": 3,
                "commandId": "start-with-discount-001",
                "discountAmountSatang": 5_000,
                "discountReason": "คูปองสมัครครั้งแรก",
            },
        )
        replay = client.post(
            "/api/v1/admin/bookings/BK-20260902-001:start",
            json={
                "expectedVersion": 3,
                "commandId": "start-with-discount-001",
                "discountAmountSatang": 5_000,
                "discountReason": "คูปองสมัครครั้งแรก",
            },
        )
        conflicting_reuse = client.post(
            "/api/v1/admin/bookings/BK-20260902-001:start",
            json={
                "expectedVersion": 3,
                "commandId": "start-with-discount-001",
                "discountAmountSatang": 4_000,
                "discountReason": "โปรโมชั่นหน้าร้าน",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    assert conflicting_reuse.status_code == 409
    assert response.json() == {
        "bookingId": "BK-20260902-001",
        "status": "IN_SERVICE",
        "version": 4,
        "subtotalAmountSatang": 60_000,
        "discountAmountSatang": 5_000,
        "discountReason": "คูปองสมัครครั้งแรก",
        "estimatedAmountSatang": 55_000,
        "tipAmountSatang": 0,
        "grossAmountSatang": 55_000,
    }
    booking = database.documents[("bookings", "booking-active-001")]
    assert booking["status"] == "IN_SERVICE"
    assert booking["serviceStartedAt"] is not None
    assert booking["discountAmountSatang"] == 5_000
    assert booking["estimatedAmountSatang"] == 55_000
    assert booking["discountAppliedBy"] == "staff-001"
    audits = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
    ]
    assert {item["eventType"] for item in audits} == {
        "BOOKING_STATUS_CHANGED",
        "BOOKING_DISCOUNT_APPLIED",
    }


def test_staff_start_service_preserves_existing_discount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    database.documents[("bookings", "booking-active-001")] = {
        "publicBookingId": "BK-20260902-001",
        "branchId": "branch_001",
        "status": "CONFIRMED",
        "version": 3,
        "assignmentState": "ASSIGNED",
        "customerListBucket": "UPCOMING",
        "subtotalAmountSatang": 60_000,
        "discountAmountSatang": 5_000,
        "discountReason": "โปรโมชั่นหน้าร้าน",
        "estimatedAmountSatang": 55_000,
        "tipAmountSatang": 0,
        "grossAmountSatang": 55_000,
        "capacityReleased": False,
    }
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="STAFF")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260902-001:start",
            json={
                "expectedVersion": 3,
                "commandId": "staff-start-service-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert response.json()["discountAmountSatang"] == 5_000
    assert response.json()["estimatedAmountSatang"] == 55_000
    discount_audits = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and str(value.get("eventType", "")).startswith("BOOKING_DISCOUNT")
    ]
    assert discount_audits == []


def test_admin_adds_service_and_updates_discount_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    fixed_now = datetime(2026, 9, 3, 3, 0, tzinfo=UTC)
    booking_start = datetime(2026, 9, 3, 10, 0, tzinfo=booking_service.BRANCH_TIMEZONE)
    database.documents.update(
        {
            ("bookings", "booking-active-001"): {
                "publicBookingId": "BK-20260903-001",
                "branchId": "branch_001",
                "status": "IN_SERVICE",
                "version": 4,
                "startAt": booking_start,
                "endAt": booking_start + timedelta(minutes=60),
                "localDate": "2026-09-03",
                "pax": 1,
                "subtotalAmountSatang": 30_000,
                "discountAmountSatang": 0,
                "estimatedAmountSatang": 30_000,
                "tipAmountSatang": 0,
                "grossAmountSatang": 30_000,
                "capacityReleased": False,
                "capacityReservation": {
                    "bucketIds": ["branch_001_20260903_1000"],
                    "units": 1,
                },
                "serviceNamesTh": ["นวดแผนไทย"],
                "serviceNamesEn": ["Traditional Thai Massage"],
            },
            ("booking_participants", "participant-001"): {
                "bookingDocId": "booking-active-001",
                "sequence": 1,
                "nickname": "Som",
            },
            ("booking_line_items", "line-original-001"): {
                "bookingDocId": "booking-active-001",
                "branchId": "branch_001",
                "serviceSnapshot": {
                    "serviceId": "traditional-thai",
                    "variantId": "traditional-thai-60",
                    "nameTh": "นวดแผนไทย",
                    "nameEn": "Traditional Thai Massage",
                    "durationMinutes": 60,
                },
                "lineTotalSatang": 30_000,
                "participantIds": ["participant-001"],
            },
            ("therapists", "therapist-001"): {
                "branchId": "branch_001",
                "displayName": "หมอเอ",
                "active": True,
            },
        }
    )
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(booking_routes, "_utc_now", lambda: fixed_now)
    previous_auth, previous_firestore = _override_dependencies(database, role="ADMIN")
    request = {
        "participantId": "participant-001",
        "serviceVariantId": "traditional-thai-60",
        "therapistId": "therapist-001",
        "date": "2026-09-03",
        "time": "11:00",
        "expectedVersion": 4,
        "commandId": "add-service-001",
        "discountAmountSatang": 5_000,
        "discountReason": "เพิ่มบริการพร้อมส่วนลด",
    }
    try:
        response = client.post("/api/v1/admin/bookings/BK-20260903-001/services", json=request)
        replay = client.post("/api/v1/admin/bookings/BK-20260903-001/services", json=request)
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    payload = response.json()
    assert payload["status"] == "IN_SERVICE"
    assert payload["version"] == 5
    assert payload["subtotalAmountSatang"] == 60_000
    assert payload["discountAmountSatang"] == 5_000
    assert payload["estimatedAmountSatang"] == 55_000
    assert payload["addedService"]["therapistName"] == "หมอเอ"
    booking = database.documents[("bookings", "booking-active-001")]
    assert booking["discountReason"] == "เพิ่มบริการพร้อมส่วนลด"
    assert booking["capacityReservation"]["additions"][0]["units"] == 1
    added_lines = [
        value
        for (collection, document_id), value in database.documents.items()
        if collection == "booking_line_items" and document_id != "line-original-001"
    ]
    assert len(added_lines) == 1
    assert added_lines[0]["source"] == "ADMIN_ADD_ON"
    audit_types = {
        value["eventType"]
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
    }
    assert audit_types == {"BOOKING_SERVICE_ADDED", "BOOKING_DISCOUNT_APPLIED"}


def test_staff_adds_catalog_service_without_changing_existing_discount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    fixed_now = datetime(2026, 9, 3, 3, 0, tzinfo=UTC)
    booking_start = datetime(2026, 9, 3, 10, 0, tzinfo=booking_service.BRANCH_TIMEZONE)
    database.documents.update(
        {
            ("bookings", "booking-active-001"): {
                "publicBookingId": "BK-20260903-001",
                "branchId": "branch_001",
                "status": "IN_SERVICE",
                "version": 4,
                "startAt": booking_start,
                "endAt": booking_start + timedelta(minutes=60),
                "localDate": "2026-09-03",
                "pax": 1,
                "subtotalAmountSatang": 30_000,
                "discountAmountSatang": 2_000,
                "discountReason": "โปรโมชั่นหน้าร้าน",
                "estimatedAmountSatang": 28_000,
                "tipAmountSatang": 0,
                "grossAmountSatang": 28_000,
                "capacityReleased": False,
                "capacityReservation": {"bucketIds": [], "units": 1},
            },
            ("booking_participants", "participant-001"): {
                "bookingDocId": "booking-active-001",
                "sequence": 1,
                "nickname": "Som",
            },
            ("therapists", "therapist-001"): {
                "branchId": "branch_001",
                "displayName": "หมอเอ",
                "active": True,
            },
        }
    )
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(booking_routes, "_utc_now", lambda: fixed_now)
    previous_auth, previous_firestore = _override_dependencies(database, role="STAFF")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260903-001/services",
            json={
                "participantId": "participant-001",
                "serviceVariantId": "traditional-thai-60",
                "therapistId": "therapist-001",
                "date": "2026-09-03",
                "time": "11:00",
                "expectedVersion": 4,
                "commandId": "staff-add-service-001",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert response.json()["discountAmountSatang"] == 2_000
    assert response.json()["estimatedAmountSatang"] == 58_000
    discount_audits = [
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and str(value.get("eventType", "")).startswith("BOOKING_DISCOUNT")
    ]
    assert discount_audits == []


def test_completing_booking_releases_original_and_added_service_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WalkInFirestore()
    database.documents.update(
        {
            ("bookings", "booking-active-001"): {
                "publicBookingId": "BK-20260903-001",
                "branchId": "branch_001",
                "status": "IN_SERVICE",
                "version": 5,
                "pax": 1,
                "subtotalAmountSatang": 60_000,
                "estimatedAmountSatang": 60_000,
                "capacityReleased": False,
                "capacityReservation": {
                    "bucketIds": ["branch_001_20260903_1000"],
                    "units": 1,
                    "additions": [
                        {
                            "lineItemId": "line-addon-001",
                            "bucketIds": ["branch_001_20260903_1100"],
                            "units": 1,
                        }
                    ],
                },
            },
            ("capacity_buckets", "branch_001_20260903_1000"): {"usedUnits": 1},
            ("capacity_buckets", "branch_001_20260903_1100"): {"usedUnits": 1},
        }
    )
    monkeypatch.setattr(booking_routes.firestore, "transactional", lambda function: function)
    previous_auth, previous_firestore = _override_dependencies(database, role="STAFF")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260903-001:complete",
            json={"expectedVersion": 5, "commandId": "complete-added-service-001"},
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert database.documents[("bookings", "booking-active-001")]["capacityReleased"]
    assert database.documents[("capacity_buckets", "branch_001_20260903_1000")]["usedUnits"] == 0
    assert database.documents[("capacity_buckets", "branch_001_20260903_1100")]["usedUnits"] == 0


def test_staff_cannot_change_discount_when_starting_service() -> None:
    previous_auth, previous_firestore = _override_dependencies(object(), role="STAFF")
    try:
        response = client.post(
            "/api/v1/admin/bookings/BK-20260902-001:start",
            json={
                "expectedVersion": 3,
                "commandId": "staff-start-discount-001",
                "discountAmountSatang": 5_000,
                "discountReason": "โปรโมชั่นหน้าร้าน",
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_admin_historical_endpoint_maps_to_recorded_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_booking(_client: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"bookingId": "BK-20260820-001", "status": "RECORDED"}

    monkeypatch.setattr(booking_routes, "create_booking", fake_create_booking)
    previous_auth, previous_firestore = _override_dependencies(object(), role="ADMIN")
    try:
        response = client.post(
            "/api/v1/admin/bookings",
            headers={"Idempotency-Key": "historical-record-001"},
            json={
                "bookingMode": "HISTORICAL_RECORD",
                "date": "2026-08-20",
                "time": "14:00",
                "phone": None,
                "bookingPrivacyAcknowledged": True,
                "consentCaptureMethod": "PAPER",
                "tipAmountSatang": 5_000,
                    "historicalPaymentSource": "BANK_TRANSFER",
                    "historicalBankAccountKey": "kbank-6073-a",
                "historicalPaidAt": "2026-08-20T15:00:00+07:00",
                "participants": [
                    {
                        "nickname": "Som",
                        "serviceVariantId": "traditional-thai-60",
                        "hasHealthInformation": False,
                        "healthDetails": None,
                        "healthConsent": True,
                    }
                ],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201, response.text
    assert captured["initial_status"] == "RECORDED"
    assert captured["admin_booking_mode"] == "HISTORICAL_RECORD"
    assert captured["tip_amount_satang"] == 5_000
    assert captured["historical_payment_source"] == "BANK_TRANSFER"
    assert captured["historical_bank_account_key"] == "kbank-6073-a"
    assert captured["historical_paid_at"] == datetime.fromisoformat(
        "2026-08-20T15:00:00+07:00"
    )


def test_admin_endpoint_rejects_tip_for_non_historical_booking() -> None:
    previous_auth, previous_firestore = _override_dependencies(object())
    try:
        response = client.post(
            "/api/v1/admin/bookings",
            headers={"Idempotency-Key": "active-tip-rejected-001"},
            json={
                "bookingMode": "STAFF_ASSISTED",
                "date": "2026-09-05",
                "time": "14:00",
                "phone": None,
                "bookingPrivacyAcknowledged": True,
                "consentCaptureMethod": "PAPER",
                "tipAmountSatang": 5_000,
                "participants": [
                    {
                        "nickname": "Som",
                        "serviceVariantId": "traditional-thai-60",
                        "hasHealthInformation": False,
                        "healthDetails": None,
                        "healthConsent": True,
                    }
                ],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 422
    assert "historical records" in response.text


def test_admin_availability_uses_authenticated_admin_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_search(_client: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"slots": [], "configurationState": "CAPACITY_UNAVAILABLE"}

    monkeypatch.setattr(booking_routes, "search_capacity_slots", fake_search)
    previous_auth, previous_firestore = _override_dependencies(WalkInFirestore())
    try:
        response = client.post(
            "/api/v1/admin/availability/search",
            json={
                "date": "2026-09-05",
                "participants": [{"serviceVariantId": "traditional-thai-60"}],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert captured["mode"] == "ADMIN"
    assert captured["date_from"] == "2026-09-05"
    assert captured["date_to"] == "2026-09-05"
