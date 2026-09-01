from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import bookings as booking_routes
from app.core.auth import require_admin_user
from app.core.errors import AdvanceWindowViolation, ValidationDomainError
from app.domains.bookings import service as booking_service
from app.infrastructure.firestore import get_firestore_client
from app.main import app

client = TestClient(app)


class Snapshot:
    def __init__(self, document_id: str, data: dict[str, object] | None) -> None:
        self.id = document_id
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, object]:
        return dict(self._data or {})


class Document:
    def __init__(self, database: WalkInFirestore, collection: str, document_id: str) -> None:
        self.database = database
        self.collection_name = collection
        self.id = document_id

    def get(self, transaction: object | None = None) -> Snapshot:
        del transaction
        return Snapshot(self.id, self.database.documents.get((self.collection_name, self.id)))


class Query:
    def __init__(self, database: WalkInFirestore, collection: str) -> None:
        self.database = database
        self.collection_name = collection

    def where(self, *_args: object, **_kwargs: object) -> Query:
        return self

    def limit(self, _value: int) -> Query:
        return self

    def stream(self, transaction: object | None = None) -> list[Snapshot]:
        del transaction
        return []

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


def _override_dependencies(
    database: object, *, role: str = "STAFF"
) -> tuple[object, object]:
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
    previous_auth, previous_firestore = _override_dependencies(
        WalkInFirestore(), role="ADMIN"
    )
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
        value
        for (collection, _), value in database.documents.items()
        if collection == "bookings"
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
        value
        for (collection, _), value in database.documents.items()
        if collection == "bookings"
    )
    assert booking["subtotalAmountSatang"] == 30_000
    assert booking["discountAmountSatang"] == 2_000
    assert booking["estimatedAmountSatang"] == 28_000
    assert booking["discountReason"] == "คูปองสมัครครั้งแรก"
    assert booking["discountAppliedBy"] == "admin-001"
    discount_audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and value.get("eventType") == "BOOKING_DISCOUNT_APPLIED"
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
        actor_id="staff-001",
        admin_booking_mode="HISTORICAL_RECORD",
        consent_capture_method="VERBAL",
        booking_privacy_acknowledged=True,
    )

    assert result["status"] == "RECORDED"
    assert result["subtotalAmountSatang"] == 30_000
    assert result["discountAmountSatang"] == 0
    assert result["estimatedAmountSatang"] == 30_000
    booking = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "bookings"
    )
    assert booking["customerListBucket"] == "HISTORY"
    assert booking["financiallyExcluded"] is False
    assert booking["historicalFinancialRecord"] is True
    assert booking["subtotalAmountSatang"] == 30_000
    assert booking["estimatedAmountSatang"] == 30_000
    assert booking["paymentStatus"] == "UNAVAILABLE"
    assert booking["capacityReleased"] is True
    assert "capacityReservation" not in booking
    assert booking["recordedBy"] == "staff-001"
    assert not any(
        collection == "capacity_buckets" for collection, _ in database.documents
    )
    assert not any(
        collection == "notification_outbox" for collection, _ in database.documents
    )
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
    )
    assert audit["eventType"] == "BOOKING_HISTORY_RECORDED"
    assert audit["subtotalAmountSatang"] == 30_000
    assert audit["discountAmountSatang"] == 0
    assert audit["estimatedAmountSatang"] == 30_000


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
    )

    assert result["subtotalAmountSatang"] == 30_000
    assert result["discountAmountSatang"] == 2_000
    assert result["estimatedAmountSatang"] == 28_000
    booking = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "bookings"
    )
    assert booking["discountReason"] == "คูปองสมัครครั้งแรก"
    assert booking["estimatedAmountSatang"] == 28_000
    assert booking["financiallyExcluded"] is False
    discount_audit = next(
        value
        for (collection, _), value in database.documents.items()
        if collection == "audit_events"
        and value.get("eventType") == "BOOKING_DISCOUNT_APPLIED"
    )
    assert discount_audit["finalAmountSatang"] == 28_000


def test_admin_historical_endpoint_maps_to_recorded_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_booking(_client: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"bookingId": "BK-20260820-001", "status": "RECORDED"}

    monkeypatch.setattr(booking_routes, "create_booking", fake_create_booking)
    previous_auth, previous_firestore = _override_dependencies(object())
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
