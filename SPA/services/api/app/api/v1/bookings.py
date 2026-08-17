from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, status
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_admin_user
from app.core.errors import ConflictDomainError, NotFoundDomainError, ValidationDomainError
from app.core.settings import get_settings
from app.core.types import BookingStatus
from app.domains.bookings.service import create_booking, serialize_booking
from app.domains.bookings.state_machine import BookingStateMachine
from app.infrastructure.firestore import get_firestore_client

router = APIRouter(tags=["bookings"])


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class ParticipantInput(ApiModel):
    nickname: str = Field(min_length=1, max_length=80)
    service_variant_id: str = Field(min_length=1)
    has_health_information: bool
    health_details: str | None = Field(default=None, max_length=1000)
    health_consent: bool


class CreateBookingRequest(ApiModel):
    branch_id: str = "branch_001"
    date: str
    time: str
    phone: str = Field(min_length=7, max_length=30)
    participants: list[ParticipantInput] = Field(min_length=1, max_length=2)
    line_id_token: str | None = Field(default=None, min_length=20, max_length=4096)


class TransitionRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=500)
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)


class StatusResolveRequest(ApiModel):
    booking_id: str
    status_token: str = Field(min_length=20)


class BookingLineLinkRequest(StatusResolveRequest):
    line_id_token: str = Field(min_length=20, max_length=4096)


def _verify_line_id_token(id_token: str) -> dict[str, object]:
    channel_id = get_settings().line_customer_login_channel_id
    if not channel_id:
        raise ValidationDomainError("LINE account linking is not configured")
    try:
        response = httpx.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": channel_id},
            timeout=10,
        )
    except httpx.HTTPError as error:
        raise ValidationDomainError(
            "LINE identity verification is temporarily unavailable"
        ) from error
    if response.status_code != 200:
        raise ValidationDomainError("LINE identity token is invalid or expired")
    payload = response.json()
    if str(payload.get("aud", "")) != channel_id or not payload.get("sub"):
        raise ValidationDomainError("LINE identity token has an invalid audience")
    return payload


@router.post("/api/v1/public/bookings", status_code=status.HTTP_201_CREATED)
async def create_public_booking(
    request: CreateBookingRequest,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if any(p.has_health_information and not p.health_details for p in request.participants):
        raise ValidationDomainError(
            "Health details are required when health information is declared"
        )
    line_identity = _verify_line_id_token(request.line_id_token) if request.line_id_token else None
    return create_booking(
        client,
        branch_id=request.branch_id,
        date=request.date,
        time=request.time,
        phone=request.phone,
        participants=[p.model_dump(by_alias=True) for p in request.participants],
        idempotency_key=idempotency_key,
        line_identity=line_identity,
    )


@router.post("/api/v1/public/bookings/status:resolve")
async def resolve_public_booking_status(
    request: StatusResolveRequest,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    matches = list(
        client.collection("bookings")
        .where("publicBookingId", "==", request.booking_id)
        .limit(1)
        .stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking status link is invalid")
    data = matches[0].to_dict() or {}
    supplied = hashlib.sha256(request.status_token.encode()).hexdigest()
    if supplied != data.get("statusTokenHash"):
        raise NotFoundDomainError("Booking status link is invalid")
    return {
        "bookingId": request.booking_id,
        "status": data.get("status"),
        "localDate": data.get("localDate"),
        "localStartTime": data.get("localStartTime"),
        "pax": data.get("pax"),
        "estimatedAmountSatang": data.get("estimatedAmountSatang"),
        "priceIncludesVat": True,
    }


@router.post("/api/v1/public/booking-line-links")
async def link_booking_to_line(
    request: BookingLineLinkRequest,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    matches = list(
        client.collection("bookings")
        .where("publicBookingId", "==", request.booking_id)
        .limit(1)
        .stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking status link is invalid")
    booking = matches[0]
    booking_data = booking.to_dict() or {}
    supplied = hashlib.sha256(request.status_token.encode()).hexdigest()
    if supplied != booking_data.get("statusTokenHash"):
        raise NotFoundDomainError("Booking status link is invalid")

    identity = _verify_line_id_token(request.line_id_token)
    line_user_id = str(identity["sub"])
    channel_id = get_settings().line_customer_login_channel_id
    line_user_hash = hashlib.sha256(line_user_id.encode()).hexdigest()
    link_ref = client.collection("line_booking_links").document(booking.id)
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> bool:
        snapshot = link_ref.get(transaction=tx)
        existing = snapshot.to_dict() or {} if snapshot.exists else {}
        if existing:
            if existing.get("lineUserId") != line_user_id:
                raise ConflictDomainError("Booking is already linked to another LINE account")
            if existing.get("active"):
                return True
        now = datetime.now(UTC)
        tx.set(
            link_ref,
            {
                "bookingDocId": booking.id,
                "lineUserId": line_user_id,
                "channelId": channel_id,
                "verifiedAt": now,
                "linkedAt": existing.get("linkedAt", now),
                "active": True,
                "version": int(existing.get("version", 0)) + 1,
            },
            merge=True,
        )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "BOOKING_LINE_LINKED",
                "bookingDocId": booking.id,
                "publicBookingId": request.booking_id,
                "actorType": "LINE_CUSTOMER",
                "actorIdHash": line_user_hash,
                "createdAt": now,
            },
        )
        return False

    idempotent = write(transaction)
    return {"bookingId": request.booking_id, "linked": True, "idempotent": idempotent}


@router.get("/api/v1/admin/bookings")
async def list_admin_bookings(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: str = "branch_001",
    local_date: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    query = client.collection("bookings").where("branchId", "==", branch_id)
    if local_date:
        query = query.where("localDate", "==", local_date)
    query = query.order_by("startAt").limit(min(max(limit, 1), 200))
    return {"items": [serialize_booking(snapshot) for snapshot in query.stream()]}


@router.get("/api/v1/admin/bookings/{booking_id}/health")
async def get_admin_booking_health(
    booking_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    matches = list(
        client.collection("bookings").where("publicBookingId", "==", booking_id).limit(1).stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking not found")
    booking_doc_id = matches[0].id
    participants = list(
        client.collection("booking_participants")
        .where("bookingDocId", "==", booking_doc_id)
        .stream()
    )
    items = []
    for snapshot in participants:
        participant = snapshot.to_dict() or {}
        health_id = participant.get("healthProfileId")
        health = (
            client.collection("health_profiles").document(str(health_id)).get()
            if health_id
            else None
        )
        health_data = health.to_dict() if health and health.exists else {}
        items.append(
            {
                "participantId": snapshot.id,
                "sequence": participant.get("sequence"),
                "nickname": participant.get("nickname"),
                "hasInformation": bool(health_data.get("hasInformation")),
                "details": health_data.get("details", ""),
                "policyVersion": health_data.get("policyVersion"),
                "retentionUntil": health_data.get("retentionUntil"),
            }
        )
    client.collection("audit_events").document().set(
        {
            "eventType": "HEALTH_DATA_VIEWED",
            "bookingDocId": booking_doc_id,
            "publicBookingId": booking_id,
            "actorType": "ADMIN_USER",
            "actorId": actor["uid"],
            "createdAt": datetime.now(UTC),
        }
    )
    return {"bookingId": booking_id, "participants": items}


@router.post("/api/v1/admin/bookings/{booking_id}:{action}")
async def transition_admin_booking(
    booking_id: str,
    action: str,
    request: TransitionRequest,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    matches = list(
        client.collection("bookings").where("publicBookingId", "==", booking_id).limit(1).stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking not found")
    booking_ref = matches[0].reference
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction):
        snapshot = booking_ref.get(transaction=tx)
        data = snapshot.to_dict() or {}
        command_ref = client.collection("admin_commands").document(
            hashlib.sha256(request.command_id.encode()).hexdigest()
        )
        command_snapshot = command_ref.get(transaction=tx)
        if command_snapshot.exists:
            return str((command_snapshot.to_dict() or {}).get("status", data.get("status"))), int(
                data.get("version", 1)
            )
        if int(data.get("version", 1)) != request.expected_version:
            raise ConflictDomainError("Booking changed; reload before trying again")
        current = BookingStatus(str(data.get("status", "")))
        now = datetime.now(UTC)
        start_at = data.get("startAt")
        no_show_reached = isinstance(start_at, datetime) and now >= start_at + timedelta(
            minutes=get_settings().no_show_grace_minutes
        )
        target = BookingStateMachine.transition(
            current,
            action,
            cancellation_reason=request.reason,
            all_therapists_assigned=data.get("assignmentState") == "ASSIGNED",
            no_show_window_reached=no_show_reached,
        )
        next_version = int(data.get("version", 1)) + 1
        update: dict[str, object] = {
            "status": target.value,
            "version": next_version,
            "updatedAt": now,
        }
        if target is BookingStatus.CANCELLED:
            update["cancellation"] = {
                "reason": request.reason,
                "cancelledAt": now,
                "cancelledBy": actor["uid"],
            }
        if target in {
            BookingStatus.CANCELLED,
            BookingStatus.COMPLETED,
            BookingStatus.NO_SHOW,
        } and not data.get("capacityReleased"):
            reservation = data.get("capacityReservation") or {}
            units = int(reservation.get("units", data.get("pax", 1)))
            bucket_refs = [
                client.collection("capacity_buckets").document(bucket_id)
                for bucket_id in reservation.get("bucketIds", [])
            ]
            bucket_snapshots = [ref.get(transaction=tx) for ref in bucket_refs]
            update["capacityReleased"] = True
            for bucket_ref, bucket_snapshot in zip(bucket_refs, bucket_snapshots, strict=True):
                bucket = bucket_snapshot.to_dict() or {}
                tx.set(
                    bucket_ref,
                    {
                        "usedUnits": max(0, int(bucket.get("usedUnits", 0)) - units),
                        "updatedAt": now,
                    },
                    merge=True,
                )
        tx.update(booking_ref, update)
        audit_ref = client.collection("audit_events").document()
        tx.set(
            audit_ref,
            {
                "eventType": "BOOKING_STATUS_CHANGED",
                "bookingDocId": booking_ref.id,
                "publicBookingId": booking_id,
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "fromStatus": current.value,
                "toStatus": target.value,
                "reason": request.reason,
                "commandId": request.command_id,
                "createdAt": now,
            },
        )
        event_ref = client.collection("notification_outbox").document()
        tx.set(
            event_ref,
            {
                "eventId": event_ref.id,
                "eventType": f"BOOKING_{target.value}",
                "aggregateId": booking_ref.id,
                "publicBookingId": booking_id,
                "state": "PENDING",
                "enqueueGeneration": 0,
                "createdAt": now,
                "updatedAt": now,
            },
        )
        tx.set(
            command_ref, {"bookingDocId": booking_ref.id, "status": target.value, "createdAt": now}
        )
        return target.value, next_version

    new_status, version = write(transaction)
    return {"bookingId": booking_id, "status": new_status, "version": version}
