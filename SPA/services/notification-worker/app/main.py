from __future__ import annotations

import json
import logging
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore, tasks_v2
from pydantic import BaseModel

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

app = FastAPI(title="SPA 49 Notification Worker", version="0.2.0", docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)


@lru_cache
def firestore_client() -> firestore.Client:
    return firestore.Client(
        project=os.getenv("GCP_PROJECT_ID", "the49-487609"),
        database=os.getenv("FIRESTORE_DATABASE", "spa-db"),
    )


class DispatchRequest(BaseModel):
    eventId: str


@app.post("/internal/v1/outbox/reconcile")
async def reconcile_outbox() -> dict[str, int]:
    project = os.getenv("GCP_PROJECT_ID", "the49-487609")
    region = os.getenv("GCP_REGION", "asia-southeast1")
    queue = os.getenv("TASK_QUEUE_NAME", "spa-line-notifications-test")
    worker_url = os.getenv("WORKER_TASK_URL")
    service_account = os.getenv("TASK_SERVICE_ACCOUNT")
    if not worker_url or not service_account:
        raise HTTPException(status_code=503, detail="Task dispatch configuration is incomplete")
    client = firestore_client()
    ready_events = list(
        client.collection("notification_outbox")
        .where("state", "in", ["PENDING", "RETRYABLE"])
        .limit(100)
        .stream()
    )
    stale_cutoff = datetime.now(UTC) - timedelta(hours=2)
    stale_events = [
        snapshot
        for snapshot in client.collection("notification_outbox")
        .where("state", "==", "ENQUEUED")
        .limit(100)
        .stream()
        if (snapshot.to_dict() or {}).get("updatedAt", datetime.now(UTC)) < stale_cutoff
    ]
    events = ready_events + stale_events
    tasks = tasks_v2.CloudTasksClient()
    parent = tasks.queue_path(project, region, queue)
    enqueued = 0
    for snapshot in events:
        event = snapshot.to_dict() or {}
        generation = int(event.get("enqueueGeneration", 0))
        if event.get("state") == "ENQUEUED":
            generation += 1
        task_name = tasks.task_path(project, region, queue, f"{snapshot.id}-{generation}")
        task = {
            "name": task_name,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{worker_url.rstrip('/')}/internal/v1/tasks/notifications",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"eventId": snapshot.id}).encode(),
                "oidc_token": {"service_account_email": service_account, "audience": worker_url},
            },
        }
        with suppress(AlreadyExists):
            tasks.create_task(parent=parent, task=task)
        snapshot.reference.set(
            {
                "state": "ENQUEUED",
                "enqueueGeneration": generation,
                "updatedAt": datetime.now(UTC),
            },
            merge=True,
        )
        enqueued += 1
    return {"scanned": len(events), "enqueued": enqueued}


def _test_prefix() -> str:
    return "[TEST] " if os.getenv("APP_ENV", "test") != "production" else ""


def _render_admin_message(event: dict[str, object], booking: dict[str, object]) -> str:
    health = (
        "\n⚠ รายละเอียดสุขภาพแสดงใน Flex Summary รายการจองใหม่"
        if booking.get("healthAlert")
        else ""
    )
    return (
        f"{_test_prefix()}SPA49 Booking\n"
        f"{event.get('eventType', 'BOOKING_UPDATE')}\n"
        f"Booking: {booking.get('publicBookingId')}\n"
        f"ลูกค้า: {booking.get('customerName')}\n"
        f"วันเวลา: {booking.get('localDate')} {booking.get('localStartTime')}\n"
        f"จำนวน: {booking.get('pax')} คน\n"
        f"สถานะ: {booking.get('status')}"
        f"{health}"
    )


def _phone_view(booking: dict[str, object]) -> tuple[str, str]:
    contact = booking.get("contact")
    contact = contact if isinstance(contact, dict) else {}
    e164 = str(contact.get("phoneE164", ""))
    if e164.startswith("+66") and len(e164) == 12:
        local = f"0{e164[3:]}"
        return f"{local[:3]}-{local[3:6]}-{local[6:]}", f"tel:{local}"
    display = str(contact.get("phoneMasked", "ไม่ระบุ"))
    return display, f"tel:{e164}" if e164 else "tel:0643654949"


def _booking_view(
    client: firestore.Client,
    *,
    booking_doc_id: str,
    booking: dict[str, object],
    admin: bool,
    include_health_details: bool = False,
) -> NotificationBookingView:
    participant_snapshots = list(
        client.collection("booking_participants")
        .where("bookingDocId", "==", booking_doc_id)
        .stream()
    )
    participant_data = {snapshot.id: snapshot.to_dict() or {} for snapshot in participant_snapshots}
    line_snapshots = list(
        client.collection("booking_line_items").where("bookingDocId", "==", booking_doc_id).stream()
    )
    def participant_view(
        *, participant_id: str, service_name: str, duration_minutes: int
    ) -> NotificationParticipantView:
        participant = participant_data.get(participant_id, {})
        values: dict[str, object] = {
            "nickname": str(participant.get("nickname") or booking.get("customerName", "ลูกค้า")),
            "service_name": service_name,
            "duration_minutes": duration_minutes,
        }
        if not admin:
            return NotificationParticipantView(**values)
        health_data: dict[str, object] = {}
        health_profile_id = participant.get("healthProfileId")
        if include_health_details and health_profile_id:
            health_snapshot = client.collection("health_profiles").document(
                str(health_profile_id)
            ).get()
            if health_snapshot.exists:
                health_data = health_snapshot.to_dict() or {}
        has_health_information = bool(
            health_data.get("hasInformation", participant.get("healthAlert", False))
        )
        return AdminNotificationParticipantView(
            **values,
            has_health_information=has_health_information,
            health_details=(
                str(health_data.get("details", "")).strip() or None
                if has_health_information
                else None
            ),
        )

    def line_sequence(snapshot: object) -> int:
        data = snapshot.to_dict() or {}  # type: ignore[attr-defined]
        participant_ids = data.get("participantIds")
        participant_ids = participant_ids if isinstance(participant_ids, list) else []
        participant = participant_data.get(str(participant_ids[0]), {}) if participant_ids else {}
        return int(participant.get("sequence", 999))

    participants: list[NotificationParticipantView] = []
    line_snapshots.sort(key=line_sequence)
    for line in line_snapshots:
        data = line.to_dict() or {}
        service = data.get("serviceSnapshot")
        service = service if isinstance(service, dict) else {}
        participant_ids = data.get("participantIds")
        participant_ids = participant_ids if isinstance(participant_ids, list) else []
        participant_id = str(participant_ids[0]) if participant_ids else ""
        participants.append(
            participant_view(
                participant_id=participant_id,
                service_name=str(
                    service.get("nameTh")
                    or service.get("nameEn")
                    or booking.get("serviceName", "บริการสปา")
                ),
                duration_minutes=int(service.get("durationMinutes", 60)),
            )
        )
    if not participants:
        fallback_id = next(iter(participant_data), "")
        participants.append(
            participant_view(
                participant_id=fallback_id,
                service_name=str(booking.get("serviceName", "บริการสปา")),
                duration_minutes=60,
            )
        )
    branch_id = str(booking.get("branchId", "branch_001"))
    branch_snapshot = client.collection("branches").document(branch_id).get()
    branch = branch_snapshot.to_dict() or {} if branch_snapshot.exists else {}
    phone_display, phone_uri = _phone_view(booking)
    values: dict[str, object] = {
        "public_booking_id": str(booking.get("publicBookingId", "")),
        "status": str(booking.get("status", "PENDING")),
        "contact_nickname": str(booking.get("customerName", "ลูกค้า")),
        "contact_phone_display": phone_display,
        "contact_phone_uri": phone_uri,
        "local_date": str(booking.get("localDate", "")),
        "local_time": str(booking.get("localStartTime", "")),
        "participants": participants,
        "pax": int(booking.get("pax", len(participants))),
        "estimated_amount_satang": int(booking.get("estimatedAmountSatang", 0)),
        "map_url": branch.get("mapUrl"),
        "admin_booking_url": (
            f"{os.getenv('ADMIN_WEB_URL', '').rstrip('/')}/?booking="
            f"{quote(str(booking.get('publicBookingId', '')))}"
            if os.getenv("ADMIN_WEB_URL")
            else None
        ),
    }
    if admin:
        return AdminNotificationBookingView(
            **values,
            health_alert=bool(booking.get("healthAlert")),
        )
    return NotificationBookingView(**values)


async def _push_line(*, token: str, destination: str, message: dict[str, object]) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": destination, "messages": [message]},
        )
    if response.status_code >= 300:
        provider_messages: list[str] = []
        with suppress(ValueError):
            payload = response.json()
            if isinstance(payload, dict):
                if payload.get("message"):
                    provider_messages.append(str(payload["message"])[:200])
                details = payload.get("details")
                if isinstance(details, list):
                    provider_messages.extend(
                        str(item.get("message", ""))[:200]
                        for item in details
                        if isinstance(item, dict) and item.get("message")
                    )
        logger.error(
            "LINE push rejected status=%s message_type=%s provider_messages=%s",
            response.status_code,
            message.get("type"),
            provider_messages,
        )
        raise RuntimeError(f"LINE provider returned HTTP {response.status_code}")


@app.post("/internal/v1/tasks/notifications")
async def dispatch_notification(
    request: DispatchRequest,
    x_cloudtasks_taskname: str | None = Header(default=None),
) -> dict[str, str]:
    if os.getenv("APP_ENV") == "production" and not x_cloudtasks_taskname:
        raise HTTPException(status_code=403, detail="Cloud Tasks header required")
    client = firestore_client()
    event_ref = client.collection("notification_outbox").document(request.eventId)
    event_snapshot = event_ref.get()
    if not event_snapshot.exists:
        raise HTTPException(status_code=404, detail="Outbox event not found")
    event = event_snapshot.to_dict() or {}
    if event.get("state") == "SENT":
        return {"status": "already-sent"}
    booking_snapshot = client.collection("bookings").document(str(event.get("aggregateId"))).get()
    if not booking_snapshot.exists:
        raise HTTPException(status_code=404, detail="Booking not found")
    now = datetime.now(UTC)
    event_ref.set({"state": "PROCESSING", "updatedAt": now}, merge=True)
    try:
        booking = booking_snapshot.to_dict() or {}
        event_type = str(event.get("eventType", "BOOKING_UPDATE"))
        delivery: dict[str, object] = {}
        if event_type == "BOOKING_CREATED":
            token = os.getenv("LINE_ADMIN_ACCESS_TOKEN", "")
            destination = os.getenv("LINE_ADMIN_GROUP_ID", "")
            if not token or not destination:
                raise RuntimeError("LINE Admin token or group ID is missing")
            view = _booking_view(
                client,
                booking_doc_id=booking_snapshot.id,
                booking=booking,
                admin=True,
                include_health_details=True,
            )
            await _push_line(
                token=token,
                destination=destination,
                message=flex_message(
                    alt_text=f"{_test_prefix()}มีรายการจองใหม่ {view.public_booking_id}",
                    bubble=render_admin_new_booking(view),
                ),
            )
            if any(participant.has_health_information for participant in view.participants):
                client.collection("audit_events").document(
                    f"health-disclosure-{event_snapshot.id}"
                ).set(
                    {
                        "eventType": "HEALTH_DATA_DISCLOSED_TO_ADMIN_LINE_GROUP",
                        "bookingDocId": booking_snapshot.id,
                        "publicBookingId": view.public_booking_id,
                        "notificationEventId": event_snapshot.id,
                        "actorType": "SYSTEM",
                        "targetType": "REGISTERED_ADMIN_LINE_GROUP",
                        "targetGroupId": destination,
                        "createdAt": datetime.now(UTC),
                    },
                    merge=True,
                )
            delivery["admin"] = "SENT"
        elif event_type in {"BOOKING_CONFIRMED", "BOOKING_PENDING_ACKNOWLEDGEMENT"}:
            existing_delivery = event.get("delivery")
            existing_delivery = existing_delivery if isinstance(existing_delivery, dict) else {}
            if event_type == "BOOKING_CONFIRMED" and existing_delivery.get("admin") != "SENT":
                admin_token = os.getenv("LINE_ADMIN_ACCESS_TOKEN", "")
                admin_destination = os.getenv("LINE_ADMIN_GROUP_ID", "")
                if not admin_token or not admin_destination:
                    raise RuntimeError("LINE Admin token or group ID is missing")
                admin_view = _booking_view(
                    client, booking_doc_id=booking_snapshot.id, booking=booking, admin=True
                )
                await _push_line(
                    token=admin_token,
                    destination=admin_destination,
                    message=flex_message(
                        alt_text=f"{_test_prefix()}ยืนยันการจอง {admin_view.public_booking_id} แล้ว",
                        bubble=render_admin_booking_confirmed(admin_view),
                    ),
                )
                event_ref.set(
                    {
                        "delivery": {**existing_delivery, "admin": "SENT"},
                        "updatedAt": datetime.now(UTC),
                    },
                    merge=True,
                )
                existing_delivery = {**existing_delivery, "admin": "SENT"}
                delivery["admin"] = "SENT"
            link_snapshot = (
                client.collection("line_booking_links").document(booking_snapshot.id).get()
            )
            link = link_snapshot.to_dict() or {} if link_snapshot.exists else {}
            line_user_id = str(link.get("lineUserId", "")) if link.get("active") else ""
            if not line_user_id:
                delivery["customer"] = "SKIPPED_NO_VERIFIED_LINK"
            else:
                token = os.getenv("LINE_CUSTOMER_ACCESS_TOKEN", "")
                if not token:
                    raise RuntimeError("LINE Customer access token is missing")
                view = _booking_view(
                    client,
                    booking_doc_id=booking_snapshot.id,
                    booking=booking,
                    admin=False,
                )
                customer_bubble = (
                    render_customer_confirmed(view)
                    if event_type == "BOOKING_CONFIRMED"
                    else render_customer_pending(view)
                )
                await _push_line(
                    token=token,
                    destination=line_user_id,
                    message=flex_message(
                        alt_text=(
                            f"{_test_prefix()}ยืนยันการจอง {view.public_booking_id} แล้ว"
                            if event_type == "BOOKING_CONFIRMED"
                            else f"{_test_prefix()}รับคำขอจอง {view.public_booking_id} แล้ว"
                        ),
                        bubble=customer_bubble,
                    ),
                )
                delivery["customer"] = "SENT"
        else:
            token = os.getenv("LINE_ADMIN_ACCESS_TOKEN", "")
            destination = os.getenv("LINE_ADMIN_GROUP_ID", "")
            if not token or not destination:
                raise RuntimeError("LINE Admin token or group ID is missing")
            await _push_line(
                token=token,
                destination=destination,
                message={"type": "text", "text": _render_admin_message(event, booking)},
            )
            delivery["admin"] = "SENT"
    except Exception as error:
        event_ref.set(
            {
                "state": "ENQUEUED",
                "lastErrorCode": type(error).__name__,
                "lastAttemptAt": datetime.now(UTC),
                "attemptCount": firestore.Increment(1),
                "updatedAt": datetime.now(UTC),
            },
            merge=True,
        )
        raise HTTPException(status_code=503, detail="Notification provider unavailable") from error
    event_ref.set(
        {
            "state": "SENT",
            "sentAt": datetime.now(UTC),
            "delivery": delivery,
            "attemptCount": firestore.Increment(1),
            "updatedAt": datetime.now(UTC),
        },
        merge=True,
    )
    return {"status": "sent"}


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, object]:
    admin_configured = bool(
        os.getenv("LINE_ADMIN_ACCESS_TOKEN") and os.getenv("LINE_ADMIN_GROUP_ID")
    )
    customer_configured = bool(os.getenv("LINE_CUSTOMER_ACCESS_TOKEN"))
    return {
        "status": "ready" if admin_configured else "degraded",
        "dependencies": {
            "templates": "ready",
            "lineAdmin": "ready" if admin_configured else "missing",
            "lineCustomer": "ready" if customer_configured else "missing",
        },
    }
