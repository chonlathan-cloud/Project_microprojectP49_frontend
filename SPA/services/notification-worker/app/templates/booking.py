from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field


class NotificationParticipantView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str
    service_name: str
    duration_minutes: int = Field(gt=0)


class AdminNotificationParticipantView(NotificationParticipantView):
    has_health_information: bool
    health_details: str | None = Field(default=None, max_length=1000)


class NotificationBookingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_booking_id: str
    status: Literal["PENDING", "CONFIRMED", "CANCELLED"]
    contact_nickname: str
    contact_phone_display: str
    contact_phone_uri: str
    local_date: str
    local_time: str
    participants: list[NotificationParticipantView] = Field(min_length=1, max_length=2)
    pax: int = Field(ge=1, le=2)
    estimated_amount_satang: int = Field(ge=0)
    map_url: str | None = None
    admin_booking_url: str | None = None


class AdminNotificationBookingView(NotificationBookingView):
    participants: list[AdminNotificationParticipantView] = Field(min_length=1, max_length=2)
    health_alert: bool


_THAI_WEEKDAYS = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")
_THAI_MONTHS = (
    "ม.ค.",
    "ก.พ.",
    "มี.ค.",
    "เม.ย.",
    "พ.ค.",
    "มิ.ย.",
    "ก.ค.",
    "ส.ค.",
    "ก.ย.",
    "ต.ค.",
    "พ.ย.",
    "ธ.ค.",
)


def _safe_action_uri(value: str | None, fallback: str) -> str:
    candidate = (value or "").strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return fallback
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return fallback
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc.encode("idna").decode("ascii"),
            quote(parsed.path, safe="/%:@-._~!$&'()*+,;="),
            quote(parsed.query, safe="=&%/:?@-._~!$'()*+,;"),
            quote(parsed.fragment, safe="=&%/:?@-._~!$'()*+,;"),
        )
    )


def _appointment(view: NotificationBookingView) -> str:
    parsed = date.fromisoformat(view.local_date)
    return (
        f"{_THAI_WEEKDAYS[parsed.weekday()]} {parsed.day} "
        f"{_THAI_MONTHS[parsed.month - 1]} {parsed.year + 543} | {view.local_time} น."
    )


def _service_lines(view: NotificationBookingView, *, size: str = "sm") -> list[dict[str, object]]:
    return [
        {
            "type": "text",
            "text": (
                f"• {participant.nickname}: {participant.service_name} "
                f"({participant.duration_minutes} นาที)"
            ),
            "size": size,
            "color": "#444444",
            "wrap": True,
        }
        for participant in view.participants
    ]


def _admin_health_contents(view: AdminNotificationBookingView) -> list[dict[str, object]]:
    contents: list[dict[str, object]] = [
        {
            "type": "text",
            "text": "🩺 ข้อมูลสุขภาพสำหรับเตรียมบริการ",
            "size": "sm",
            "color": "#991B1B",
            "weight": "bold",
            "wrap": True,
        }
    ]
    disclosed = False
    for participant in view.participants:
        if not participant.has_health_information:
            continue
        disclosed = True
        details = (participant.health_details or "").strip()
        contents.append(
            {
                "type": "text",
                "text": (
                    f"• {participant.nickname}: {details}"
                    if details
                    else f"• {participant.nickname}: แจ้งข้อมูลสุขภาพ แต่ไม่ได้ระบุรายละเอียด"
                ),
                "size": "xs",
                "color": "#7F1D1D",
                "margin": "sm",
                "wrap": True,
            }
        )
    if not disclosed:
        contents.append(
            {
                "type": "text",
                "text": "มีข้อมูลสุขภาพที่ต้องตรวจสอบ แต่ไม่พบรายละเอียด",
                "size": "xs",
                "color": "#7F1D1D",
                "margin": "sm",
                "wrap": True,
            }
        )
    return contents


def render_admin_new_booking(view: AdminNotificationBookingView) -> dict[str, object]:
    body: list[dict[str, object]] = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": f"#{view.public_booking_id}",
                    "size": "xs",
                    "color": "#888888",
                    "flex": 1,
                },
                {
                    "type": "text",
                    "text": "⏳ รอการยืนยัน",
                    "size": "xs",
                    "color": "#D97706",
                    "weight": "bold",
                    "align": "end",
                    "flex": 1,
                },
            ],
        },
        {"type": "separator", "margin": "md"},
        {
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "👤 ข้อมูลลูกค้า",
                    "weight": "bold",
                    "size": "sm",
                    "color": "#5A4B3A",
                },
                {
                    "type": "text",
                    "text": f"• ชื่อ: {view.contact_nickname}",
                    "size": "sm",
                    "color": "#333333",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"• เบอร์โทร: {view.contact_phone_display}",
                    "size": "sm",
                    "color": "#333333",
                },
            ],
        },
        {
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "📅 รายละเอียดการนวด",
                    "weight": "bold",
                    "size": "sm",
                    "color": "#5A4B3A",
                },
                {
                    "type": "text",
                    "text": f"• วัน-เวลา: {_appointment(view)}",
                    "size": "sm",
                    "color": "#333333",
                    "weight": "bold",
                    "wrap": True,
                },
                *_service_lines(view),
                {
                    "type": "text",
                    "text": f"• จำนวน: {view.pax} ท่าน",
                    "size": "sm",
                    "color": "#333333",
                },
            ],
        },
    ]
    if view.health_alert:
        body.append(
            {
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "paddingAll": "md",
                "backgroundColor": "#FEF2F2",
                "cornerRadius": "md",
                "contents": _admin_health_contents(view),
            }
        )
    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🔔 มีรายการจองใหม่!",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "size": "lg",
                }
            ],
            "backgroundColor": "#5A4B3A",
        },
        "body": {"type": "box", "layout": "vertical", "contents": body},
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "📞 โทรหาลูกค้า",
                        "uri": view.contact_phone_uri,
                    },
                    "style": "secondary",
                    "height": "sm",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "✅ ยืนยันการจอง",
                        "text": f"ยืนยันการจอง {view.public_booking_id}",
                    },
                    "style": "primary",
                    "color": "#5A4B3A",
                    "height": "sm",
                },
            ],
        },
    }


def render_customer_pending(view: NotificationBookingView) -> dict[str, object]:
    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#5A4B3A",
            "contents": [
                {
                    "type": "text",
                    "text": "⏳ รับคำขอจองแล้ว",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "size": "md",
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": f"รหัสการจอง #{view.public_booking_id}",
                    "size": "sm",
                    "weight": "bold",
                },
                {
                    "type": "text",
                    "text": f"วัน-เวลา: {_appointment(view)}",
                    "size": "sm",
                    "wrap": True,
                },
                *_service_lines(view, size="xs"),
                {
                    "type": "text",
                    "text": "ร้านกำลังตรวจสอบ กรุณารอข้อความยืนยันอีกครั้ง",
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True,
                },
            ],
        },
    }


def render_admin_booking_confirmed(view: AdminNotificationBookingView) -> dict[str, object]:
    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#2F5D50",
            "contents": [
                {
                    "type": "text",
                    "text": "✅ ยืนยันการจองแล้ว",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "size": "md",
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": f"#{view.public_booking_id}",
                    "weight": "bold",
                    "size": "sm",
                },
                {
                    "type": "text",
                    "text": f"ลูกค้า: {view.contact_nickname}",
                    "size": "sm",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"วัน-เวลา: {_appointment(view)}",
                    "size": "sm",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "สถานะถูกเปลี่ยนเป็น ยืนยันแล้ว",
                    "size": "xs",
                    "color": "#2F5D50",
                    "weight": "bold",
                },
            ],
        },
    }


def render_customer_confirmed(view: NotificationBookingView) -> dict[str, object]:
    price = f"{view.estimated_amount_satang / 100:,.2f} บาท (รวม VAT แล้ว)"
    details: list[dict[str, object]] = [
        {
            "type": "text",
            "text": "📌 รายละเอียดนัดหมาย",
            "weight": "bold",
            "size": "sm",
            "color": "#2F5D50",
        },
        {
            "type": "text",
            "text": f"• รหัสการจอง: #{view.public_booking_id}",
            "size": "xs",
            "color": "#444444",
        },
        {
            "type": "text",
            "text": f"• วัน-เวลา: {_appointment(view)}",
            "size": "sm",
            "color": "#111111",
            "weight": "bold",
            "wrap": True,
        },
        *_service_lines(view, size="xs"),
        {
            "type": "text",
            "text": f"• จำนวน: {view.pax} ท่าน",
            "size": "xs",
            "color": "#444444",
        },
        {
            "type": "text",
            "text": f"• ราคาประเมิน: {price}",
            "size": "xs",
            "color": "#444444",
            "wrap": True,
        },
    ]
    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "✅ ยืนยันการจองเรียบร้อยแล้ว",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "size": "md",
                }
            ],
            "backgroundColor": "#2F5D50",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"ขอขอบคุณ คุณ{view.contact_nickname} ที่เลือกใช้บริการครับ/ค่ะ",
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True,
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": details,
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "paddingAll": "md",
                    "backgroundColor": "#F4F7F5",
                    "cornerRadius": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "ℹ️ ข้อแนะนำก่อนรับบริการ",
                            "size": "xs",
                            "color": "#2F5D50",
                            "weight": "bold",
                        },
                        {
                            "type": "text",
                            "text": (
                                "• กรุณามาถึงก่อนเวลานัด 10 นาที\n"
                                "• หากต้องการเปลี่ยนแปลงเวลานัด "
                                "กรุณาแจ้งล่วงหน้าอย่างน้อย 1 วัน"
                            ),
                            "size": "xs",
                            "color": "#555555",
                            "margin": "xs",
                            "wrap": True,
                        },
                    ],
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "📍 แผนที่ร้าน",
                        "uri": _safe_action_uri(view.map_url, "https://maps.google.com"),
                    },
                    "style": "secondary",
                    "height": "sm",
                }
            ],
        },
    }


def flex_message(*, alt_text: str, bubble: dict[str, object]) -> dict[str, object]:
    return {"type": "flex", "altText": alt_text[:400], "contents": bubble}
