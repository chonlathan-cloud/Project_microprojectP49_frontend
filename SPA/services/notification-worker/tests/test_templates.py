import json

import pytest
from pydantic import ValidationError

from app.templates.booking import (
    AdminNotificationBookingView,
    AdminNotificationParticipantView,
    NotificationBookingView,
    NotificationParticipantView,
    flex_message,
    render_admin_booking_confirmed,
    render_admin_new_booking,
    render_customer_confirmed,
    render_customer_pending,
)


def base_values() -> dict[str, object]:
    return {
        "public_booking_id": "BK-20260815-001",
        "status": "PENDING",
        "contact_nickname": "Som",
        "contact_phone_display": "081-***-5678",
        "contact_phone_uri": "tel:0812345678",
        "local_date": "2026-08-15",
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
        "branch_name": "SPA 49",
        "branch_address": (
            "53/72 ถนนเฉลิมพระเกียรติ ร.9 แขวงหนองบอน "
            "เขตประเวศ กรุงเทพมหานคร 10250"
        ),
        "admin_booking_url": "https://admin.example/?booking=BK-20260815-001",
    }


def admin_values(*, health_details: str | None = None) -> dict[str, object]:
    values = base_values()
    values["participants"] = [
        AdminNotificationParticipantView(
            nickname="Som",
            service_name="Aroma Therapy",
            duration_minutes=60,
            has_health_information=health_details is not None,
            health_details=health_details,
        )
    ]
    return values


def test_customer_projection_rejects_health_fields() -> None:
    with pytest.raises(ValidationError):
        NotificationBookingView(**base_values(), health_alert=True)


def test_customer_template_contains_no_health_key() -> None:
    payload = render_customer_confirmed(
        NotificationBookingView(**{**base_values(), "status": "CONFIRMED"})
    )
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "health" not in serialized
    assert "allergy" not in serialized


def test_admin_template_displays_health_detail_for_registered_group() -> None:
    payload = render_admin_new_booking(
        AdminNotificationBookingView(
            **admin_values(health_details="แพ้น้ำมันลาเวนเดอร์"), health_alert=True
        )
    )
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "ข้อมูลสุขภาพสำหรับเตรียมบริการ" in serialized
    assert "som: แพ้น้ำมันลาเวนเดอร์" in serialized
    assert "เปิดรายละเอียดในระบบ admin" not in serialized


def test_admin_template_marks_missing_declared_detail() -> None:
    values = admin_values()
    values["participants"] = [
        AdminNotificationParticipantView(
            nickname="Som",
            service_name="Aroma Therapy",
            duration_minutes=60,
            has_health_information=True,
            health_details=None,
        )
    ]
    payload = render_admin_new_booking(
        AdminNotificationBookingView(**values, health_alert=True)
    )
    assert "ไม่ได้ระบุรายละเอียด" in json.dumps(payload, ensure_ascii=False)


def test_admin_template_stays_within_flex_payload_budget_at_input_limits() -> None:
    values = admin_values()
    values["pax"] = 2
    values["participants"] = [
        AdminNotificationParticipantView(
            nickname=f"Guest {index}",
            service_name="Aroma Therapy",
            duration_minutes=120,
            has_health_information=True,
            health_details="x" * 1000,
        )
        for index in (1, 2)
    ]
    payload = render_admin_new_booking(
        AdminNotificationBookingView(**values, health_alert=True)
    )
    assert len(json.dumps(payload, ensure_ascii=False).encode()) < 30_000


def test_admin_flex_uses_line_message_action() -> None:
    bubble = render_admin_new_booking(
        AdminNotificationBookingView(**admin_values(), health_alert=False)
    )
    confirm = bubble["footer"]["contents"][1]
    assert confirm["action"] == {
        "type": "message",
        "label": "✅ ยืนยันการจอง",
        "text": "ยืนยันการจอง BK-20260815-001",
    }
    message = flex_message(alt_text="new booking", bubble=bubble)
    assert message["type"] == "flex"
    assert message["altText"] == "new booking"


def test_confirmed_walk_in_without_phone_has_no_call_or_confirm_action() -> None:
    values = admin_values()
    values.update(
        {
            "status": "CONFIRMED",
            "contact_phone_display": "ไม่มีเบอร์ติดต่อ",
            "contact_phone_uri": None,
            "booking_source": "ADMIN_WEB",
        }
    )
    bubble = render_admin_new_booking(
        AdminNotificationBookingView(**values, health_alert=False)
    )
    serialized = json.dumps(bubble, ensure_ascii=False)
    assert "ยืนยันแล้ว • Walk-in" in serialized
    assert "โทรหาลูกค้า" not in serialized
    assert "ยืนยันการจอง" not in serialized
    assert bubble["footer"]["contents"] == [
        {
            "type": "button",
            "action": {
                "type": "uri",
                "label": "เปิดรายการจอง",
                "uri": "https://admin.example/?booking=BK-20260815-001",
            },
            "style": "primary",
            "color": "#5A4B3A",
            "height": "sm",
        }
    ]


def test_customer_flex_contains_price_and_map() -> None:
    values = {**base_values(), "status": "CONFIRMED", "map_url": "https://maps.example/spa49"}
    bubble = render_customer_confirmed(NotificationBookingView(**values))
    serialized = json.dumps(bubble, ensure_ascii=False)
    assert "600.00 บาท (รวม VAT แล้ว)" in serialized
    assert "📍 สถานที่นัดหมาย" in serialized
    assert "SPA 49" in serialized
    assert "53/72 ถนนเฉลิมพระเกียรติ ร.9" in serialized
    assert bubble["footer"]["contents"][0]["action"]["label"] == "ดูเส้นทางไป SPA 49"
    assert "https://maps.example/spa49" in serialized


def test_customer_flex_percent_encodes_non_ascii_map_uri() -> None:
    values = {
        **base_values(),
        "status": "CONFIRMED",
        "map_url": "https://www.bing.com/maps?q=ถนนเฉลิมพระเกียรติ กรุงเทพ",
    }
    bubble = render_customer_confirmed(NotificationBookingView(**values))
    uri = bubble["footer"]["contents"][0]["action"]["uri"]
    assert uri.startswith("https://www.bing.com/maps?q=")
    assert "ถนน" not in uri
    assert " " not in uri
    assert "%E0%B8" in uri


@pytest.mark.parametrize("map_url", [None, "", "javascript:alert(1)"])
def test_customer_flex_hides_map_action_without_safe_destination(map_url: str | None) -> None:
    values = {**base_values(), "status": "CONFIRMED", "map_url": map_url}
    bubble = render_customer_confirmed(NotificationBookingView(**values))
    assert "footer" not in bubble
    serialized = json.dumps(bubble, ensure_ascii=False)
    assert "📍 สถานที่นัดหมาย" in serialized
    assert "53/72 ถนนเฉลิมพระเกียรติ ร.9" in serialized


def test_pending_and_admin_confirmed_templates_are_privacy_safe() -> None:
    customer = render_customer_pending(NotificationBookingView(**base_values()))
    admin = render_admin_booking_confirmed(
        AdminNotificationBookingView(
            **{**admin_values(health_details="allergy"), "status": "CONFIRMED"},
            health_alert=True,
        )
    )
    serialized = json.dumps([customer, admin], ensure_ascii=False).lower()
    assert "health_details" not in serialized
    assert "allergy" not in serialized
