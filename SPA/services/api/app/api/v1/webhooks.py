from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from app.core.settings import get_settings
from app.domains.customers.line_friendship import (
    friendship_ref,
    webhook_friendship_record,
)
from app.infrastructure.firestore import get_firestore_client
from app.integrations.line_identity import line_identity_hash

router = APIRouter(prefix="/api/v1/webhooks/line", tags=["line-webhooks"])

Channel = Literal["customer", "admin"]
CONFIRM_COMMAND = re.compile(r"^ยืนยันการจอง\s+(BK-[A-Za-z0-9-]+)$")


def _channel_secret(channel: Channel) -> str:
    variable = (
        "LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET"
        if channel == "customer"
        else "LINE_ADMIN_MESSAGING_CHANNEL_SECRET"
    )
    secret = os.getenv(variable, "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LINE webhook channel secret is not configured",
        )
    return secret


def _valid_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


def _dedupe_key(channel: Channel, event: dict[str, object]) -> str:
    webhook_event_id = event.get("webhookEventId")
    if webhook_event_id:
        return f"{channel}_{webhook_event_id}"
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{channel}_fallback_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _source_projection(event: dict[str, object]) -> dict[str, object]:
    source = event.get("source")
    if not isinstance(source, dict):
        return {}
    return {
        "sourceType": source.get("type"),
        "hasUserId": bool(source.get("userId")),
        "hasGroupId": bool(source.get("groupId")),
        "hasRoomId": bool(source.get("roomId")),
    }


def _capture_admin_group_candidate(
    client: firestore.Client,
    *,
    channel: Channel,
    event: dict[str, object],
) -> None:
    if channel != "admin":
        return
    source = event.get("source")
    if not isinstance(source, dict) or source.get("type") != "group":
        return
    group_id = source.get("groupId")
    if not isinstance(group_id, str) or not group_id:
        return
    now = datetime.now(UTC)
    candidate_id = hashlib.sha256(group_id.encode("utf-8")).hexdigest()
    ref = client.collection("line_group_candidates").document(candidate_id)
    snapshot = ref.get()
    record: dict[str, object] = {
        "channel": channel,
        "sourceType": "group",
        "groupId": group_id,
        "lastSeenAt": now,
    }
    if not snapshot.exists:
        record["firstSeenAt"] = now
    ref.set(record, merge=True)


def _capture_customer_friend_state(
    client: firestore.Client,
    *,
    channel: Channel,
    event: dict[str, object],
) -> None:
    if channel != "customer" or event.get("type") not in {"follow", "unfollow"}:
        return
    source = event.get("source")
    if not isinstance(source, dict) or source.get("type") != "user":
        return
    line_user_id = source.get("userId")
    if not isinstance(line_user_id, str) or not line_user_id:
        return
    event_time = datetime.now(UTC)
    if isinstance(event.get("timestamp"), (int, float)):
        event_time = datetime.fromtimestamp(float(event["timestamp"]) / 1000, UTC)
    friend_status = "FOLLOWING" if event.get("type") == "follow" else "BLOCKED"
    channel_id = get_settings().line_customer_login_channel_id
    identity_ref = client.collection("customer_identity_links").document(
        line_identity_hash(line_user_id)
    )
    membership_ref = friendship_ref(
        client, line_user_id=line_user_id, channel_id=channel_id
    )
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> None:
        identity_snapshot = identity_ref.get(transaction=tx)
        identity = identity_snapshot.to_dict() or {} if identity_snapshot.exists else {}
        tx.set(
            membership_ref,
            webhook_friendship_record(
                channel_id=channel_id,
                friend_status=friend_status,
                observed_at=event_time,
            ),
            merge=True,
        )
        # Following the OA is not consent to create a CRM profile. Only update
        # an existing identity/customer that was created by an explicit flow.
        if not identity_snapshot.exists:
            return
        identity_data: dict[str, object] = {
            "friendStatus": friend_status,
            "active": True,
            "updatedAt": event_time,
        }
        customer_data: dict[str, object] = {
            "friendStatus": friend_status,
            "updatedAt": event_time,
        }
        if event.get("type") == "follow":
            followed_at = identity.get("followedAt", event_time)
            identity_data["followedAt"] = followed_at
            customer_data["followedAt"] = followed_at
        else:
            identity_data["unfollowedAt"] = event_time
            customer_data["unfollowedAt"] = event_time
        tx.set(identity_ref, identity_data, merge=True)
        customer_id = identity.get("customerId")
        if customer_id:
            customer_ref = client.collection("customers").document(str(customer_id))
            tx.set(customer_ref, customer_data, merge=True)

    write(transaction)


def _process_admin_command(
    client: firestore.Client,
    *,
    event: dict[str, object],
    webhook_ref,
) -> None:
    message = event.get("message")
    source = event.get("source")
    if not isinstance(message, dict) or message.get("type") != "text":
        return
    match = CONFIRM_COMMAND.fullmatch(str(message.get("text", "")).strip())
    if not match:
        return
    configured_group = os.getenv("LINE_ADMIN_GROUP_ID", "")
    if (
        not configured_group
        or not isinstance(source, dict)
        or source.get("type") != "group"
        or source.get("groupId") != configured_group
        or not source.get("userId")
    ):
        webhook_ref.set(
            {"processingState": "REJECTED", "processedAt": datetime.now(UTC)},
            merge=True,
        )
        return
    booking_id = match.group(1)
    matches = list(
        client.collection("bookings").where("publicBookingId", "==", booking_id).limit(1).stream()
    )
    if not matches:
        webhook_ref.set(
            {
                "processingState": "REJECTED",
                "result": "BOOKING_NOT_FOUND",
                "processedAt": datetime.now(UTC),
            },
            merge=True,
        )
        return
    booking_ref = matches[0].reference
    transaction = client.transaction()

    @firestore.transactional
    def confirm(tx: firestore.Transaction) -> str:
        snapshot = booking_ref.get(transaction=tx)
        booking = snapshot.to_dict() or {}
        current = str(booking.get("status", ""))
        now = datetime.now(UTC)
        if current != "PENDING":
            return current
        tx.update(
            booking_ref,
            {
                "status": "CONFIRMED",
                "version": int(booking.get("version", 1)) + 1,
                "updatedAt": now,
            },
        )
        audit_ref = client.collection("audit_events").document()
        tx.set(
            audit_ref,
            {
                "eventType": "BOOKING_STATUS_CHANGED",
                "bookingDocId": booking_ref.id,
                "publicBookingId": booking_id,
                "actorType": "LINE_GROUP_APPROVER",
                "actorId": str(source["userId"]),
                "groupId": configured_group,
                "fromStatus": "PENDING",
                "toStatus": "CONFIRMED",
                "webhookEventId": event.get("webhookEventId"),
                "createdAt": now,
            },
        )
        outbox_ref = client.collection("notification_outbox").document()
        tx.set(
            outbox_ref,
            {
                "eventId": outbox_ref.id,
                "eventType": "BOOKING_CONFIRMED",
                "aggregateId": booking_ref.id,
                "publicBookingId": booking_id,
                "state": "PENDING",
                "enqueueGeneration": 0,
                "createdAt": now,
                "updatedAt": now,
            },
        )
        return "CONFIRMED"

    result = confirm(transaction)
    webhook_ref.set(
        {"processingState": "PROCESSED", "result": result, "processedAt": datetime.now(UTC)},
        merge=True,
    )


async def _receive(
    channel: Channel,
    request: Request,
    signature: str | None,
    client: firestore.Client,
) -> dict[str, int | str]:
    raw_body = await request.body()
    if not signature or not _valid_signature(raw_body, signature, _channel_secret(channel)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid LINE webhook signature",
        )
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid LINE webhook body") from error
    events = payload.get("events", []) if isinstance(payload, dict) else []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="LINE webhook events must be an array")

    accepted = 0
    duplicates = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        _capture_admin_group_candidate(client, channel=channel, event=event)
        key = _dedupe_key(channel, event)
        record = {
            "dedupeKey": key,
            "channel": channel,
            "eventType": event.get("type"),
            "timestamp": event.get("timestamp"),
            "deliveryIsRedelivery": bool(
                isinstance(event.get("deliveryContext"), dict)
                and event["deliveryContext"].get("isRedelivery")
            ),
            **_source_projection(event),
            "processingState": "RECEIVED",
            "receivedAt": datetime.now(UTC),
        }
        try:
            webhook_ref = client.collection("line_webhook_events").document(key)
            webhook_ref.create(record)
            accepted += 1
            _capture_customer_friend_state(client, channel=channel, event=event)
            if channel == "admin":
                _process_admin_command(client, event=event, webhook_ref=webhook_ref)
        except AlreadyExists:
            duplicates += 1

    return {"status": "ok", "accepted": accepted, "duplicates": duplicates}


@router.post("/customer")
async def customer_webhook(
    request: Request,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    x_line_signature: Annotated[str | None, Header(alias="x-line-signature")] = None,
) -> dict[str, int | str]:
    return await _receive("customer", request, x_line_signature, client)


@router.post("/admin")
async def admin_webhook(
    request: Request,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    x_line_signature: Annotated[str | None, Header(alias="x-line-signature")] = None,
) -> dict[str, int | str]:
    return await _receive("admin", request, x_line_signature, client)
