from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import _render_admin_message, _test_prefix, app
from app.templates.booking import AdminNotificationBookingView, AdminNotificationParticipantView


def test_non_production_messages_are_prefixed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    assert _test_prefix() == "[TEST] "


def test_legacy_admin_message_does_not_copy_unprojected_root_health_detail(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    message = _render_admin_message(
        {"eventType": "BOOKING_CREATED"},
        {
            "publicBookingId": "BK-TEST",
            "customerName": "Guest",
            "localDate": "2026-08-20",
            "localStartTime": "10:00",
            "pax": 1,
            "status": "PENDING",
            "healthAlert": True,
            "healthDetails": "must never leave Firestore",
        },
    )
    assert message.startswith("[TEST]")
    assert "รายละเอียดสุขภาพแสดงใน Flex Summary" in message
    assert "must never leave Firestore" not in message


class FakeDocument:
    def __init__(self, document_id: str, data: dict[str, object]) -> None:
        self.id = document_id
        self.exists = True
        self.data = data
        self.writes: list[dict[str, object]] = []

    def get(self) -> FakeDocument:
        return self

    def to_dict(self) -> dict[str, object]:
        return self.data

    def set(self, values: dict[str, object], *, merge: bool = False) -> None:
        self.writes.append({**values, "_merge": merge})


class FakeCollection:
    def __init__(self, documents: dict[str, FakeDocument]) -> None:
        self.documents = documents

    def document(self, document_id: str) -> FakeDocument:
        return self.documents.setdefault(document_id, FakeDocument(document_id, {}))


class FakeClient:
    def __init__(self) -> None:
        self.event = FakeDocument(
            "event-1",
            {
                "eventType": "BOOKING_CREATED",
                "aggregateId": "booking-1",
                "state": "PENDING",
            },
        )
        self.booking = FakeDocument("booking-1", {"publicBookingId": "BK-TEST"})
        self.audit_documents: dict[str, FakeDocument] = {}

    def collection(self, name: str) -> FakeCollection:
        if name == "notification_outbox":
            return FakeCollection({"event-1": self.event})
        if name == "bookings":
            return FakeCollection({"booking-1": self.booking})
        if name == "audit_events":
            return FakeCollection(self.audit_documents)
        raise AssertionError(f"Unexpected collection: {name}")


def test_health_disclosure_to_admin_group_is_audited_without_detail(monkeypatch) -> None:
    database = FakeClient()
    view = AdminNotificationBookingView(
        public_booking_id="BK-TEST",
        status="PENDING",
        contact_nickname="Som",
        contact_phone_display="081-234-5678",
        contact_phone_uri="tel:0812345678",
        local_date="2026-08-20",
        local_time="16:00",
        participants=[
            AdminNotificationParticipantView(
                nickname="Som",
                service_name="Aroma Therapy",
                duration_minutes=60,
                has_health_information=True,
                health_details="แพ้น้ำมันลาเวนเดอร์",
            )
        ],
        pax=1,
        estimated_amount_satang=60000,
        health_alert=True,
    )

    async def fake_push_line(**_kwargs: object) -> None:
        return None

    monkeypatch.setenv("LINE_ADMIN_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("LINE_ADMIN_GROUP_ID", "group-admin")
    monkeypatch.setattr("app.main.firestore_client", lambda: database)
    monkeypatch.setattr("app.main._booking_view", lambda *_args, **_kwargs: view)
    monkeypatch.setattr("app.main._push_line", fake_push_line)

    response = TestClient(app).post(
        "/internal/v1/tasks/notifications", json={"eventId": "event-1"}
    )

    assert response.status_code == 200
    audit = database.audit_documents["health-disclosure-event-1"].writes[0]
    assert audit["eventType"] == "HEALTH_DATA_DISCLOSED_TO_ADMIN_LINE_GROUP"
    assert audit["targetGroupId"] == "group-admin"
    assert "แพ้น้ำมันลาเวนเดอร์" not in str(audit)
