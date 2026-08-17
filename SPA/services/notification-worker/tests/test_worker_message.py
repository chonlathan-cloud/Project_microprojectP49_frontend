from app.main import _render_admin_message, _test_prefix


def test_non_production_messages_are_prefixed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    assert _test_prefix() == "[TEST] "


def test_admin_message_uses_boolean_health_indicator_only(monkeypatch) -> None:
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
    assert "กรุณาตรวจสอบใน Admin Web" in message
    assert "must never leave Firestore" not in message
