from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationParticipantView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str
    service_name: str
    duration_minutes: int = Field(gt=0)


class NotificationBookingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_booking_id: str
    status: Literal["PENDING", "CONFIRMED", "CANCELLED"]
    contact_nickname: str
    contact_phone_display: str
    local_date_label: str
    local_time: str
    participants: list[NotificationParticipantView] = Field(min_length=1, max_length=2)
    pax: int = Field(ge=1, le=2)
    estimated_amount_satang: int = Field(ge=0)
    map_url: str | None = None


class AdminNotificationBookingView(NotificationBookingView):
    health_alert: bool


def _participant_lines(view: NotificationBookingView) -> list[str]:
    return [
        f"{participant.nickname}: {participant.service_name} ({participant.duration_minutes} min)"
        for participant in view.participants
    ]


def render_customer_pending(view: NotificationBookingView) -> dict[str, object]:
    return {
        "template": "customer_pending_v1",
        "bookingId": view.public_booking_id,
        "status": view.status,
        "appointment": f"{view.local_date_label} {view.local_time}",
        "participants": _participant_lines(view),
        "estimatedAmountSatang": view.estimated_amount_satang,
        "notice": "Your request is pending store confirmation.",
    }


def render_admin_new_booking(view: AdminNotificationBookingView) -> dict[str, object]:
    payload: dict[str, object] = {
        "template": "admin_new_booking_v1",
        "bookingId": view.public_booking_id,
        "status": view.status,
        "contact": {
            "nickname": view.contact_nickname,
            "phoneDisplay": view.contact_phone_display,
        },
        "appointment": f"{view.local_date_label} {view.local_time}",
        "participants": _participant_lines(view),
        "pax": view.pax,
    }
    if view.health_alert:
        payload["healthIndicator"] = "Health information requires review in Admin"
    return payload
