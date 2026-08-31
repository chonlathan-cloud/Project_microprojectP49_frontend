from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1 import bookings
from app.infrastructure.firestore import get_firestore_client
from app.integrations.line_identity import line_identity_hash
from app.main import app


class Snapshot:
    def __init__(self, document_id: str, data: dict[str, object]) -> None:
        self.id = document_id
        self._data = data

    def to_dict(self) -> dict[str, object]:
        return dict(self._data)


class Query:
    def __init__(self, snapshots: list[Snapshot]) -> None:
        self.snapshots = snapshots
        self.filters: list[tuple[str, str, object]] = []
        self.limit_value = 100
        self.cursor: list[object] | None = None

    def where(self, field: str, operator: str, value: object):
        self.filters.append((field, operator, value))
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def start_after(self, cursor: list[object]):
        self.cursor = cursor
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def stream(self):
        return iter(self.snapshots[: self.limit_value])


class Database:
    def __init__(self, snapshots: list[Snapshot]) -> None:
        self.query = Query(snapshots)

    def collection(self, name: str) -> Query:
        assert name == "bookings"
        return self.query


def settings():
    return type(
        "Settings",
        (),
        {
            "line_customer_login_channel_id": "booking-channel",
            "line_customer_messaging_channel_secret": "test-cursor-secret",
        },
    )()


def test_customer_booking_list_is_line_scoped_and_omits_sensitive_fields(monkeypatch) -> None:
    as_of = datetime(2026, 8, 24, 0, tzinfo=UTC)
    database = Database(
        [
            Snapshot(
                "booking-doc-1",
                {
                    "publicBookingId": "BK-20260825-ABC123",
                    "status": "CONFIRMED",
                    "startAt": datetime(2026, 8, 25, 3, tzinfo=UTC),
                    "localDate": "2026-08-25",
                    "localStartTime": "10:00",
                    "timezone": "Asia/Bangkok",
                    "serviceNamesTh": ["นวดอโรม่า"],
                    "serviceNamesEn": ["Aroma Therapy"],
                    "pax": 1,
                    "estimatedAmountSatang": 50000,
                    "contact": {"phoneE164": "+66812345678"},
                    "statusTokenHash": "must-not-leak",
                },
            )
        ]
    )
    previous = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[get_firestore_client] = lambda: database
    monkeypatch.setattr(
        bookings,
        "_verify_line_id_token",
        lambda _token: {"sub": "line-user-1", "aud": "booking-channel"},
    )
    monkeypatch.setattr(bookings, "get_settings", settings)
    monkeypatch.setattr(bookings, "_utc_now", lambda: as_of)
    try:
        response = TestClient(app).post(
            "/api/v1/customer/bookings:list",
            json={
                "lineIdToken": "line-id-token-with-minimum-length",
                "view": "UPCOMING",
                "pageSize": 20,
            },
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_firestore_client, None)
        else:
            app.dependency_overrides[get_firestore_client] = previous

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [
        {
            "bookingId": "BK-20260825-ABC123",
            "status": "CONFIRMED",
            "localDate": "2026-08-25",
            "localStartTime": "10:00",
            "timezone": "Asia/Bangkok",
            "serviceNamesTh": ["นวดอโรม่า"],
            "serviceNamesEn": ["Aroma Therapy"],
            "pax": 1,
            "estimatedAmountSatang": 50000,
            "priceIncludesVat": True,
            "paymentStatus": "UNAVAILABLE",
            "paidAmountSatang": 0,
        }
    ]
    assert "+66812345678" not in response.text
    assert "must-not-leak" not in response.text
    expected_hash = line_identity_hash("line-user-1", "booking-channel")
    assert ("lineIdentityHash", "==", expected_hash) in database.query.filters
    assert not any(field == "customerListBucket" for field, _, _ in database.query.filters)


def test_customer_booking_view_uses_status_and_appointment_time() -> None:
    as_of = datetime(2026, 8, 24, 0, tzinfo=UTC)

    assert bookings._customer_booking_view(
        {"status": "CONFIRMED", "startAt": datetime(2026, 8, 25, 3, tzinfo=UTC)},
        as_of=as_of,
    ) == "UPCOMING"
    assert bookings._customer_booking_view(
        {"status": "CONFIRMED", "startAt": datetime(2026, 8, 20, 3, tzinfo=UTC)},
        as_of=as_of,
    ) == "HISTORY"
    assert bookings._customer_booking_view(
        {"status": "CANCELLED", "startAt": datetime(2026, 8, 25, 3, tzinfo=UTC)},
        as_of=as_of,
    ) == "HISTORY"
    assert bookings._customer_booking_view(
        {"status": "IN_SERVICE", "startAt": datetime(2026, 8, 23, 3, tzinfo=UTC)},
        as_of=as_of,
    ) == "UPCOMING"


def test_customer_booking_history_includes_past_confirmed_and_future_terminal(
    monkeypatch,
) -> None:
    as_of = datetime(2026, 8, 24, 0, tzinfo=UTC)
    database = Database(
        [
            Snapshot(
                "future-cancelled",
                {
                    "publicBookingId": "BK-CANCELLED",
                    "status": "CANCELLED",
                    "startAt": datetime(2026, 8, 26, 3, tzinfo=UTC),
                },
            ),
            Snapshot(
                "future-confirmed",
                {
                    "publicBookingId": "BK-FUTURE",
                    "status": "CONFIRMED",
                    "startAt": datetime(2026, 8, 25, 3, tzinfo=UTC),
                },
            ),
            Snapshot(
                "past-in-service",
                {
                    "publicBookingId": "BK-IN-SERVICE",
                    "status": "IN_SERVICE",
                    "startAt": datetime(2026, 8, 23, 3, tzinfo=UTC),
                },
            ),
            Snapshot(
                "past-confirmed",
                {
                    "publicBookingId": "BK-PAST",
                    "status": "CONFIRMED",
                    "startAt": datetime(2026, 8, 20, 3, tzinfo=UTC),
                },
            ),
            Snapshot(
                "completed",
                {
                    "publicBookingId": "BK-COMPLETED",
                    "status": "COMPLETED",
                    "startAt": datetime(2026, 8, 19, 3, tzinfo=UTC),
                },
            ),
        ]
    )
    previous = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[get_firestore_client] = lambda: database
    monkeypatch.setattr(
        bookings,
        "_verify_line_id_token",
        lambda _token: {"sub": "line-user-1", "aud": "booking-channel"},
    )
    monkeypatch.setattr(bookings, "get_settings", settings)
    monkeypatch.setattr(bookings, "_utc_now", lambda: as_of)
    try:
        response = TestClient(app).post(
            "/api/v1/customer/bookings:list",
            json={
                "lineIdToken": "line-id-token-with-minimum-length",
                "view": "HISTORY",
                "pageSize": 20,
            },
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_firestore_client, None)
        else:
            app.dependency_overrides[get_firestore_client] = previous

    assert response.status_code == 200
    assert [item["bookingId"] for item in response.json()["items"]] == [
        "BK-CANCELLED",
        "BK-PAST",
        "BK-COMPLETED",
    ]


def test_customer_booking_cursor_is_signed_and_bound_to_view(monkeypatch) -> None:
    monkeypatch.setattr(bookings, "get_settings", settings)
    start_at = datetime(2026, 8, 25, 3, tzinfo=UTC)
    token = bookings._encode_customer_cursor(
        view="UPCOMING",
        start_at=start_at,
        document_id="booking-doc-1",
        as_of=datetime(2026, 8, 24, 0, tzinfo=UTC),
    )

    assert bookings._decode_customer_cursor(token, expected_view="UPCOMING") == (
        start_at,
        "booking-doc-1",
        datetime(2026, 8, 24, 0, tzinfo=UTC),
    )
    try:
        bookings._decode_customer_cursor(token, expected_view="HISTORY")
    except Exception as error:
        assert getattr(error, "code", None) == "VALIDATION_FAILED"
    else:
        raise AssertionError("A cursor must not be reusable for another view")
