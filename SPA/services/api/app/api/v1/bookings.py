from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, status
from fastapi import Query as FastAPIQuery
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_admin_user
from app.core.errors import (
    ConflictDomainError,
    NotFoundDomainError,
    PermissionDenied,
    ValidationDomainError,
)
from app.core.settings import get_settings
from app.core.types import BookingStatus
from app.domains.bookings.service import (
    _variant,
    create_booking,
    customer_list_bucket,
    serialize_booking,
)
from app.domains.bookings.state_machine import BookingStateMachine
from app.domains.capacity.availability import search_capacity_slots
from app.infrastructure.firestore import get_firestore_client
from app.integrations.line_identity import (
    line_identity_hash,
)
from app.integrations.line_identity import (
    verify_line_id_token as _verify_line_id_token,
)

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


class CreateAdminBookingRequest(ApiModel):
    booking_mode: Literal["WALK_IN", "STAFF_ASSISTED", "HISTORICAL_RECORD"] = (
        "STAFF_ASSISTED"
    )
    branch_id: str = "branch_001"
    date: str
    time: str
    phone: str | None = Field(default=None, max_length=30)
    participants: list[ParticipantInput] = Field(min_length=1, max_length=2)
    booking_privacy_acknowledged: bool
    consent_capture_method: Literal["VERBAL", "PAPER"]
    discount_amount_satang: int = Field(default=0, ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)
    tip_amount_satang: int = Field(default=0, ge=0)


class AdminAvailabilityParticipant(ApiModel):
    service_variant_id: str = Field(min_length=1)


class AdminAvailabilityRequest(ApiModel):
    branch_id: str = "branch_001"
    date: str
    participants: list[AdminAvailabilityParticipant] = Field(min_length=1, max_length=2)


class TransitionRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=500)
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)


class StatusResolveRequest(ApiModel):
    booking_id: str
    status_token: str = Field(min_length=20)


class BookingLineLinkRequest(StatusResolveRequest):
    line_id_token: str = Field(min_length=20, max_length=4096)


class CustomerBookingListRequest(ApiModel):
    line_id_token: str = Field(min_length=20, max_length=4096)
    view: Literal["UPCOMING", "HISTORY"] = "UPCOMING"
    page_size: int = Field(default=20, ge=1, le=50)
    page_token: str | None = Field(default=None, max_length=2048)


CUSTOMER_BOOKING_SCAN_BATCH_SIZE = 100
CUSTOMER_ACTIVE_STATUSES = {"PENDING", "CONFIRMED"}
ADMIN_BOOKING_SCAN_BATCH_SIZE = 100


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _cursor_secret() -> bytes:
    secret = get_settings().line_customer_messaging_channel_secret
    if not secret:
        raise ValidationDomainError("Booking pagination is not configured")
    return secret.encode()


def _encode_customer_cursor(
    *, view: str, start_at: datetime, document_id: str, as_of: datetime
) -> str:
    payload = json.dumps(
        {
            "view": view,
            "startAt": start_at.isoformat(),
            "documentId": document_id,
            "asOf": as_of.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        _cursor_secret(), b"customer-bookings:v1:" + payload, hashlib.sha256
    ).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def _decode_customer_cursor(
    token: str, *, expected_view: str
) -> tuple[datetime, str, datetime]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        expected = hmac.new(
            _cursor_secret(), b"customer-bookings:v1:" + payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        state = json.loads(payload)
        if state.get("view") != expected_view:
            raise ValueError
        start_at = datetime.fromisoformat(str(state["startAt"]))
        document_id = str(state["documentId"])
        as_of_value = state.get("asOf")
        as_of = datetime.fromisoformat(str(as_of_value)) if as_of_value else _utc_now()
        if not document_id or start_at.tzinfo is None or as_of.tzinfo is None:
            raise ValueError
        return start_at, document_id, as_of
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidationDomainError("Invalid customer booking page token") from error


def _admin_booking_filter_fingerprint(
    *, branch_id: str, local_date: str | None, status_filter: str | None, search: str
) -> str:
    payload = json.dumps(
        {
            "branchId": branch_id,
            "localDate": local_date,
            "status": status_filter,
            "search": search.casefold(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _encode_admin_booking_cursor(
    *, start_at: datetime, document_id: str, filter_fingerprint: str
) -> str:
    payload = json.dumps(
        {
            "startAt": start_at.isoformat(),
            "documentId": document_id,
            "filterFingerprint": filter_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        _cursor_secret(), b"admin-bookings:v1:" + payload, hashlib.sha256
    ).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def _decode_admin_booking_cursor(
    token: str, *, expected_filter_fingerprint: str
) -> tuple[datetime, str]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        expected = hmac.new(
            _cursor_secret(), b"admin-bookings:v1:" + payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        state = json.loads(payload)
        if state.get("filterFingerprint") != expected_filter_fingerprint:
            raise ValueError
        start_at = datetime.fromisoformat(str(state["startAt"]))
        document_id = str(state["documentId"])
        if not document_id or start_at.tzinfo is None:
            raise ValueError
        return start_at, document_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidationDomainError("Invalid Admin booking page token") from error


def _admin_booking_matches_search(data: dict[str, object], search: str) -> bool:
    needle = search.strip().casefold()
    if not needle:
        return True
    contact = data.get("contact")
    contact_data = contact if isinstance(contact, dict) else {}
    values = (
        data.get("publicBookingId", ""),
        data.get("customerName", ""),
        contact_data.get("phoneMasked", ""),
        contact_data.get("phoneE164", ""),
    )
    haystack = " ".join(str(value) for value in values).casefold()
    if needle in haystack:
        return True
    compact_needle = "".join(character for character in needle if character.isalnum())
    compact_haystack = "".join(character for character in haystack if character.isalnum())
    return bool(compact_needle) and compact_needle in compact_haystack


def _aggregation_count(query: object) -> int:
    results = query.count(alias="count").get()  # type: ignore[attr-defined]
    if not results or not results[0]:
        return 0
    return int(results[0][0].value)


def _customer_booking_view(data: dict[str, object], *, as_of: datetime) -> str:
    status_value = str(data.get("status", ""))
    start_at = data.get("startAt")
    upcoming = status_value == "IN_SERVICE" or (
        status_value in CUSTOMER_ACTIVE_STATUSES
        and isinstance(start_at, datetime)
        and start_at >= as_of
    )
    return "UPCOMING" if upcoming else "HISTORY"


def _serialize_customer_booking(snapshot: firestore.DocumentSnapshot) -> dict[str, object]:
    data = snapshot.to_dict() or {}
    service_names_th = data.get("serviceNamesTh")
    service_names_en = data.get("serviceNamesEn")
    return {
        "bookingId": data.get("publicBookingId", snapshot.id),
        "status": data.get("status"),
        "localDate": data.get("localDate"),
        "localStartTime": data.get("localStartTime"),
        "timezone": data.get("timezone", "Asia/Bangkok"),
        "serviceNamesTh": service_names_th
        if isinstance(service_names_th, list)
        else [data.get("serviceNameTh") or data.get("serviceName") or ""],
        "serviceNamesEn": service_names_en
        if isinstance(service_names_en, list)
        else [data.get("serviceNameEn") or data.get("serviceName") or ""],
        "pax": data.get("pax"),
        "estimatedAmountSatang": data.get("estimatedAmountSatang"),
        "priceIncludesVat": bool(data.get("priceIncludesVat", True)),
        "paymentStatus": data.get("paymentStatus", "UNAVAILABLE"),
        "paidAmountSatang": int(data.get("paidAmountSatang", 0)),
    }


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
        source="LINE_CUSTOMER" if line_identity else "GUEST_WEB",
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
    line_user_hash = line_identity_hash(line_user_id, channel_id)
    link_ref = client.collection("line_booking_links").document(booking.id)
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> bool:
        snapshot = link_ref.get(transaction=tx)
        existing = snapshot.to_dict() or {} if snapshot.exists else {}
        if existing and existing.get("lineUserId") != line_user_id:
            raise ConflictDomainError("Booking is already linked to another LINE account")
        idempotent = bool(existing.get("active"))
        now = datetime.now(UTC)
        if not idempotent:
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
            booking.reference,
            {
                "lineIdentityHash": line_user_hash,
                "customerListBucket": customer_list_bucket(str(booking_data.get("status", ""))),
                "updatedAt": now,
            },
            merge=True,
        )
        if not idempotent:
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
        return idempotent

    idempotent = write(transaction)
    return {"bookingId": request.booking_id, "linked": True, "idempotent": idempotent}


@router.post("/api/v1/customer/bookings:list")
async def list_customer_bookings(
    request: CustomerBookingListRequest,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    identity = _verify_line_id_token(request.line_id_token)
    identity_hash = line_identity_hash(
        str(identity["sub"]),
        str(identity.get("aud") or get_settings().line_customer_login_channel_id),
    )
    direction = (
        firestore.Query.ASCENDING if request.view == "UPCOMING" else firestore.Query.DESCENDING
    )
    base_query = (
        client.collection("bookings")
        .where("lineIdentityHash", "==", identity_hash)
        .order_by("startAt", direction=direction)
        .order_by("__name__", direction=direction)
    )
    as_of = _utc_now()
    query = base_query
    if request.page_token:
        start_at, document_id, as_of = _decode_customer_cursor(
            request.page_token, expected_view=request.view
        )
        query = query.start_after([start_at, document_id])

    matching_snapshots: list[firestore.DocumentSnapshot] = []
    while len(matching_snapshots) <= request.page_size:
        snapshots = list(query.limit(CUSTOMER_BOOKING_SCAN_BATCH_SIZE).stream())
        for snapshot in snapshots:
            data = snapshot.to_dict() or {}
            if _customer_booking_view(data, as_of=as_of) == request.view:
                matching_snapshots.append(snapshot)
                if len(matching_snapshots) > request.page_size:
                    break
        if len(matching_snapshots) > request.page_size:
            break
        if len(snapshots) < CUSTOMER_BOOKING_SCAN_BATCH_SIZE:
            break
        last_data = snapshots[-1].to_dict() or {}
        last_start_at = last_data.get("startAt")
        if not isinstance(last_start_at, datetime):
            break
        query = base_query.start_after([last_start_at, snapshots[-1].id])

    page = matching_snapshots[: request.page_size]
    next_page_token = None
    if len(matching_snapshots) > request.page_size and page:
        last_data = page[-1].to_dict() or {}
        last_start_at = last_data.get("startAt")
        if isinstance(last_start_at, datetime):
            next_page_token = _encode_customer_cursor(
                view=request.view,
                start_at=last_start_at,
                document_id=page[-1].id,
                as_of=as_of,
            )
    return {
        "items": [_serialize_customer_booking(snapshot) for snapshot in page],
        "nextPageToken": next_page_token,
    }


@router.get("/api/v1/admin/bookings")
async def list_admin_bookings(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: str = "branch_001",
    local_date: str | None = None,
    page_size: Annotated[int, FastAPIQuery(alias="pageSize", ge=1, le=100)] = 25,
    page_token: Annotated[
        str | None, FastAPIQuery(alias="pageToken", min_length=20, max_length=2048)
    ] = None,
    status_filter: Annotated[
        BookingStatus | None, FastAPIQuery(alias="status")
    ] = None,
    search: Annotated[str | None, FastAPIQuery(max_length=100)] = None,
    limit: Annotated[int | None, FastAPIQuery(ge=1, le=200)] = None,
) -> dict[str, object]:
    effective_page_size = min(limit or page_size, 100)
    normalized_search = (search or "").strip()
    status_value = status_filter.value if status_filter else None
    filter_fingerprint = _admin_booking_filter_fingerprint(
        branch_id=branch_id,
        local_date=local_date,
        status_filter=status_value,
        search=normalized_search,
    )

    collection = client.collection("bookings")
    base_query = collection.where("branchId", "==", branch_id)
    if local_date:
        base_query = base_query.where("localDate", "==", local_date)
    if status_value:
        base_query = base_query.where("status", "==", status_value)
    base_query = base_query.order_by(
        "startAt", direction=firestore.Query.DESCENDING
    ).order_by("__name__", direction=firestore.Query.DESCENDING)

    query = base_query
    if page_token:
        start_at, document_id = _decode_admin_booking_cursor(
            page_token, expected_filter_fingerprint=filter_fingerprint
        )
        query = query.start_after([start_at, document_id])

    matching_snapshots: list[firestore.DocumentSnapshot] = []
    while len(matching_snapshots) <= effective_page_size:
        snapshots = list(query.limit(ADMIN_BOOKING_SCAN_BATCH_SIZE).stream())
        for snapshot in snapshots:
            data = snapshot.to_dict() or {}
            if _admin_booking_matches_search(data, normalized_search):
                matching_snapshots.append(snapshot)
                if len(matching_snapshots) > effective_page_size:
                    break
        if len(matching_snapshots) > effective_page_size:
            break
        if len(snapshots) < ADMIN_BOOKING_SCAN_BATCH_SIZE:
            break
        last_data = snapshots[-1].to_dict() or {}
        last_start_at = last_data.get("startAt")
        if not isinstance(last_start_at, datetime):
            break
        query = base_query.start_after([last_start_at, snapshots[-1].id])

    page = matching_snapshots[:effective_page_size]
    next_page_token = None
    if len(matching_snapshots) > effective_page_size and page:
        last_data = page[-1].to_dict() or {}
        last_start_at = last_data.get("startAt")
        if isinstance(last_start_at, datetime):
            next_page_token = _encode_admin_booking_cursor(
                start_at=last_start_at,
                document_id=page[-1].id,
                filter_fingerprint=filter_fingerprint,
            )

    pending_count = _aggregation_count(
        collection.where("branchId", "==", branch_id).where("status", "==", "PENDING")
    )
    unassigned_count = _aggregation_count(
        collection.where("branchId", "==", branch_id)
        .where("status", "==", "CONFIRMED")
        .where("assignmentState", "==", "UNASSIGNED")
    )
    return {
        "items": [serialize_booking(snapshot) for snapshot in page],
        "nextPageToken": next_page_token,
        "hasMore": next_page_token is not None,
        "pageSize": effective_page_size,
        "summary": {"pending": pending_count, "unassigned": unassigned_count},
    }


@router.post("/api/v1/admin/bookings", status_code=status.HTTP_201_CREATED)
async def create_admin_booking(
    request: CreateAdminBookingRequest,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if any(p.has_health_information and not p.health_details for p in request.participants):
        raise ValidationDomainError(
            "Health details are required when health information is declared"
        )
    if not request.booking_privacy_acknowledged:
        raise ValidationDomainError("Booking privacy acknowledgement is required")
    historical_record = request.booking_mode == "HISTORICAL_RECORD"
    if request.discount_amount_satang > 0 and actor.get("role") != "ADMIN":
        raise PermissionDenied("Only ADMIN may apply a booking discount")
    if request.tip_amount_satang > 0 and not historical_record:
        raise ValidationDomainError("Tips may only be recorded for historical records")
    return create_booking(
        client,
        branch_id=request.branch_id,
        date=request.date,
        time=request.time,
        phone=request.phone,
        participants=[p.model_dump(by_alias=True) for p in request.participants],
        idempotency_key=idempotency_key,
        source="ADMIN_WEB",
        initial_status="RECORDED" if historical_record else "CONFIRMED",
        actor_id=str(actor["uid"]),
        admin_booking_mode=request.booking_mode,
        consent_capture_method=request.consent_capture_method,
        booking_privacy_acknowledged=request.booking_privacy_acknowledged,
        actor_role=str(actor.get("role", "")),
        discount_amount_satang=request.discount_amount_satang,
        discount_reason=request.discount_reason,
        tip_amount_satang=request.tip_amount_satang,
    )


@router.post("/api/v1/admin/availability/search")
async def search_admin_booking_availability(
    request: AdminAvailabilityRequest,
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    variants = [
        _variant(client, participant.service_variant_id)[1]
        for participant in request.participants
    ]
    if any(item.required_pax == 2 for item in variants) and (
        len(variants) != 2 or len({item.id for item in variants}) != 1
    ):
        raise ValidationDomainError("Invalid participant configuration")
    return search_capacity_slots(
        client,
        branch_id=request.branch_id,
        date_from=request.date,
        date_to=request.date,
        duration_minutes=max(item.duration_minutes for item in variants),
        units=len(variants),
        mode="ADMIN",
    )


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
            "customerListBucket": customer_list_bucket(target.value),
            "version": next_version,
            "updatedAt": now,
        }
        if target is BookingStatus.IN_SERVICE:
            update["serviceStartedAt"] = now
        if target is BookingStatus.COMPLETED:
            update["serviceCompletedAt"] = now
        if target is BookingStatus.CANCELLED:
            update["cancellation"] = {
                "reason": request.reason,
                "cancelledAt": now,
                "cancelledBy": actor["uid"],
            }
            if current is BookingStatus.RECORDED:
                update["financiallyExcluded"] = True
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
        if current is not BookingStatus.RECORDED:
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
