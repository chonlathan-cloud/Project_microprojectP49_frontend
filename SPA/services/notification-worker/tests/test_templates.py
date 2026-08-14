import json

import pytest
from pydantic import ValidationError

from app.templates.booking import (
    AdminNotificationBookingView,
    NotificationBookingView,
    NotificationParticipantView,
    render_admin_new_booking,
    render_customer_pending,
)


def base_values() -> dict[str, object]:
    return {
        "public_booking_id": "BK-20260815-001",
        "status": "PENDING",
        "contact_nickname": "Som",
        "contact_phone_display": "081-***-5678",
        "local_date_label": "15 Aug 2026",
        "local_time": "14:00",
        "participants": [
            NotificationParticipantView(
                nickname="Som",
                service_name="Aroma Therapy",
                duration_minutes=60,
            )
        ],
        "pax": 1,
        "estimated_amount_satang": 60000,
    }


def test_customer_projection_rejects_health_fields() -> None:
    with pytest.raises(ValidationError):
        NotificationBookingView(**base_values(), health_alert=True)


def test_customer_template_contains_no_health_key() -> None:
    payload = render_customer_pending(NotificationBookingView(**base_values()))
    serialized = json.dumps(payload).lower()
    assert "health" not in serialized
    assert "allergy" not in serialized


def test_admin_template_has_indicator_but_not_detail() -> None:
    payload = render_admin_new_booking(
        AdminNotificationBookingView(**base_values(), health_alert=True)
    )
    serialized = json.dumps(payload).lower()
    assert "health information requires review" in serialized
    assert "allergy" not in serialized
