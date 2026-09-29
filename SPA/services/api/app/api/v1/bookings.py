from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, status
from fastapi import Query as FastAPIQuery
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.auth import require_admin_user
from app.core.errors import (
    CapacityUnavailable,
    ConflictDomainError,
    HistoricalCorrectionRequired,
    NotFoundDomainError,
    PermissionDenied,
    ValidationDomainError,
)
from app.core.settings import get_settings
from app.core.types import BookingStatus
from app.domains.bookings.plan import build_booking_plan
from app.domains.bookings.pricing import validate_fixed_discount
from app.domains.bookings.service import (
    _bucket_id,
    _validate_operating_hours,
    _validate_walk_in_window,
    _variant,
    create_booking,
    customer_list_bucket,
    serialize_booking,
)
from app.domains.bookings.state_machine import BookingStateMachine
from app.domains.capacity.availability import search_capacity_slots
from app.domains.capacity.buckets import required_bucket_starts
from app.infrastructure.firestore import get_firestore_client
from app.infrastructure.firestore_historical_corrections import (
    FirestoreHistoricalCorrectionRepository,
)
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


class ParticipantServiceInput(ApiModel):
    service_variant_id: str = Field(min_length=1, max_length=160)


class ParticipantInput(ApiModel):
    nickname: str = Field(min_length=1, max_length=80)
    service_variant_id: str | None = Field(default=None, min_length=1, max_length=160)
    services: list[ParticipantServiceInput] = Field(default_factory=list, max_length=3)
    has_health_information: bool
    health_details: str | None = Field(default=None, max_length=1000)
    health_consent: bool

    @model_validator(mode="after")
    def validate_service_contract(self) -> ParticipantInput:
        if bool(self.service_variant_id) == bool(self.services):
            raise ValueError("Provide either serviceVariantId or services")
        return self


class CreateBookingRequest(ApiModel):
    branch_id: str = "branch_001"
    date: str
    time: str
    phone: str = Field(min_length=7, max_length=30)
    participants: list[ParticipantInput] = Field(min_length=1, max_length=2)
    line_id_token: str | None = Field(default=None, min_length=20, max_length=4096)


class CreateAdminBookingRequest(ApiModel):
    booking_mode: Literal["WALK_IN", "STAFF_ASSISTED", "HISTORICAL_RECORD"] = "STAFF_ASSISTED"
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
    historical_payment_source: Literal["CASH", "BANK_TRANSFER"] | None = None
    historical_paid_at: datetime | None = None
    historical_bank_account_key: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_historical_payment(self) -> CreateAdminBookingRequest:
        historical = self.booking_mode == "HISTORICAL_RECORD"
        if historical and (
            self.historical_payment_source is None or self.historical_paid_at is None
        ):
            raise ValueError(
                "Historical records require payment source and authoritative paid time"
            )
        if not historical and (
            self.historical_payment_source is not None
            or self.historical_paid_at is not None
            or self.historical_bank_account_key is not None
        ):
            raise ValueError("Historical payment evidence is only valid for historical records")
        if historical and self.historical_payment_source == "BANK_TRANSFER":
            if self.historical_bank_account_key is None:
                raise ValueError("Bank transfer requires a bank account")
        elif self.historical_bank_account_key is not None:
            raise ValueError("Bank account is only valid for bank transfer")
        if (
            self.historical_paid_at is not None
            and (
                self.historical_paid_at.tzinfo is None
                or self.historical_paid_at.utcoffset() is None
            )
        ):
            raise ValueError("Historical paid time must include a timezone offset")
        return self


class AdminAvailabilityParticipant(ApiModel):
    service_variant_id: str | None = Field(default=None, min_length=1, max_length=160)
    services: list[ParticipantServiceInput] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_service_contract(self) -> AdminAvailabilityParticipant:
        if bool(self.service_variant_id) == bool(self.services):
            raise ValueError("Provide either serviceVariantId or services")
        return self


class AdminAvailabilityRequest(ApiModel):
    branch_id: str = "branch_001"
    date: str
    participants: list[AdminAvailabilityParticipant] = Field(min_length=1, max_length=2)


class TransitionRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=500)
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)
    discount_amount_satang: int | None = Field(default=None, ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)


class VoidHistoricalBookingRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)


class AddBookingServiceRequest(ApiModel):
    participant_id: str = Field(min_length=1, max_length=160)
    service_variant_id: str = Field(min_length=1, max_length=160)
    therapist_id: str = Field(min_length=1, max_length=160)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)
    discount_amount_satang: int | None = Field(default=None, ge=0, multiple_of=100)
    discount_reason: str | None = Field(default=None, max_length=200)


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
BANGKOK = ZoneInfo("Asia/Bangkok")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _actor_branch_ids(actor: dict[str, object]) -> tuple[str, ...]:
    raw = actor.get("branchIds")
    if isinstance(raw, list):
        values = tuple(str(value) for value in raw if value)
        if values:
            return values
    return (get_settings().default_branch_id,)


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


def _decode_customer_cursor(token: str, *, expected_view: str) -> tuple[datetime, str, datetime]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
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
    signature = hmac.new(_cursor_secret(), b"admin-bookings:v1:" + payload, hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def _decode_admin_booking_cursor(
    token: str, *, expected_filter_fingerprint: str
) -> tuple[datetime, str]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
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
    status_filter: Annotated[BookingStatus | None, FastAPIQuery(alias="status")] = None,
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
    base_query = base_query.order_by("startAt", direction=firestore.Query.DESCENDING).order_by(
        "__name__", direction=firestore.Query.DESCENDING
    )

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
    if historical_record and actor.get("role") != "ADMIN":
        raise PermissionDenied("Only ADMIN may record paid historical bookings")
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
        historical_payment_source=request.historical_payment_source,
        historical_paid_at=request.historical_paid_at,
        historical_bank_account_key=request.historical_bank_account_key,
    )


@router.post("/api/v1/admin/availability/search")
async def search_admin_booking_availability(
    request: AdminAvailabilityRequest,
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    plan = build_booking_plan(
        [participant.model_dump(by_alias=True) for participant in request.participants],
        lambda variant_id: _variant(client, variant_id),
        max_services_per_participant=get_settings().max_services_per_participant,
    )
    return search_capacity_slots(
        client,
        branch_id=request.branch_id,
        date_from=request.date,
        date_to=request.date,
        participant_duration_minutes=list(plan.participant_duration_minutes),
        mode="ADMIN",
    )


@router.get("/api/v1/admin/bookings/{booking_id}")
async def get_admin_booking_detail(
    booking_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    matches = list(
        client.collection("bookings").where("publicBookingId", "==", booking_id).limit(1).stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking not found")
    booking_snapshot = matches[0]
    booking_data = booking_snapshot.to_dict() or {}
    participant_snapshots = list(
        client.collection("booking_participants")
        .where("bookingDocId", "==", booking_snapshot.id)
        .stream()
    )
    participant_snapshots.sort(key=lambda item: int((item.to_dict() or {}).get("sequence", 0)))
    line_snapshots = list(
        client.collection("booking_line_items")
        .where("bookingDocId", "==", booking_snapshot.id)
        .stream()
    )
    services_by_participant: dict[str, list[tuple[int, int, dict[str, object]]]] = {}
    participant_by_id = {
        snapshot.id: snapshot.to_dict() or {} for snapshot in participant_snapshots
    }
    service_items: list[dict[str, object]] = []
    for line_snapshot in line_snapshots:
        line = line_snapshot.to_dict() or {}
        service = line.get("serviceSnapshot")
        if not isinstance(service, dict):
            continue
        participant_ids = [str(value) for value in line.get("participantIds") or []]
        participant_sequence = int(line.get("participantSequence", line.get("sequence", 999)))
        line_sequence = int(line.get("sequence", 999))
        for participant_id in participant_ids:
            services_by_participant.setdefault(participant_id, []).append(
                (participant_sequence, line_sequence, service)
            )
        participant_id = participant_ids[0] if participant_ids else ""
        participant_names = [
            str(participant_by_id.get(item, {}).get("nickname") or "Guest")
            for item in participant_ids
        ]
        participant = participant_by_id.get(participant_id, {})
        assignment = line.get("assignment")
        assignment_data = assignment if isinstance(assignment, dict) else {}
        scheduled_start = line.get("scheduledStartAt")
        if not isinstance(scheduled_start, datetime):
            scheduled_start = booking_data.get("serviceStartedAt") or booking_data.get("startAt")
        scheduled_end = line.get("scheduledEndAt")
        if not isinstance(scheduled_end, datetime) and isinstance(scheduled_start, datetime):
            scheduled_end = scheduled_start + timedelta(
                minutes=int(service.get("durationMinutes", 0))
            )
        service_items.append(
            {
                "lineItemId": line_snapshot.id,
                "participantId": participant_id,
                "participantName": participant.get("nickname") or "Guest",
                "participantIds": participant_ids,
                "participantNames": participant_names,
                "sequence": int(
                    line.get("sequence", participant.get("sequence", len(service_items) + 1))
                ),
                "source": line.get("source", "ORIGINAL"),
                "serviceId": service.get("serviceId"),
                "variantId": service.get("variantId"),
                "serviceNameTh": service.get("nameTh"),
                "serviceNameEn": service.get("nameEn"),
                "durationMinutes": int(service.get("durationMinutes", 0)),
                "lineTotalSatang": int(line.get("lineTotalSatang", 0)),
                "therapistId": assignment_data.get("therapistId"),
                "therapistName": assignment_data.get("therapistName"),
                "scheduledStartAt": (
                    scheduled_start.isoformat() if isinstance(scheduled_start, datetime) else None
                ),
                "scheduledEndAt": (
                    scheduled_end.isoformat() if isinstance(scheduled_end, datetime) else None
                ),
            }
        )
    service_items.sort(key=lambda item: (int(item["sequence"]), str(item["lineItemId"])))
    assigned_ids = [str(item) for item in booking_data.get("therapistIds") or []]
    assigned_names = [
        value.strip()
        for value in str(booking_data.get("therapistName") or "").split(",")
        if value.strip()
    ]
    therapist_names = {
        therapist_id: assigned_names[index]
        for index, therapist_id in enumerate(assigned_ids)
        if index < len(assigned_names)
    }
    participant_index = {snapshot.id: index for index, snapshot in enumerate(participant_snapshots)}
    for item in service_items:
        if item.get("therapistId"):
            continue
        item_participant_ids = [str(value) for value in item.get("participantIds") or []]
        line_therapist_ids = [
            assigned_ids[index]
            for participant_id in item_participant_ids
            if 0 <= (index := participant_index.get(participant_id, -1)) < len(assigned_ids)
        ]
        line_therapist_names = [
            therapist_names[therapist_id]
            for therapist_id in line_therapist_ids
            if therapist_id in therapist_names
        ]
        if line_therapist_ids:
            item["therapistId"] = line_therapist_ids[0]
            item["therapistIds"] = line_therapist_ids
        if line_therapist_names:
            item["therapistName"] = " + ".join(line_therapist_names)
            item["therapistNames"] = line_therapist_names
    participants = []
    for index, participant_snapshot in enumerate(participant_snapshots):
        participant = participant_snapshot.to_dict() or {}
        assignment = participant.get("assignment")
        assignment_data = assignment if isinstance(assignment, dict) else {}
        therapist_id = assignment_data.get("therapistId")
        if not therapist_id and index < len(assigned_ids):
            therapist_id = assigned_ids[index]
        participant_services = [
            item[2] for item in sorted(services_by_participant.get(participant_snapshot.id, []))
        ]
        service = participant_services[0] if participant_services else {}
        participants.append(
            {
                "participantId": participant_snapshot.id,
                "sequence": int(participant.get("sequence", index + 1)),
                "nickname": participant.get("nickname") or f"Guest {index + 1}",
                "serviceNameTh": service.get("nameTh")
                or booking_data.get("serviceNameTh")
                or booking_data.get("serviceName"),
                "serviceNameEn": service.get("nameEn")
                or booking_data.get("serviceNameEn")
                or booking_data.get("serviceName"),
                "durationMinutes": int(service.get("durationMinutes", 0)),
                "serviceNamesTh": [item.get("nameTh") for item in participant_services],
                "serviceNamesEn": [item.get("nameEn") for item in participant_services],
                "totalDurationMinutes": sum(
                    int(item.get("durationMinutes", 0)) for item in participant_services
                ),
                "therapistId": str(therapist_id) if therapist_id else None,
            }
        )
    next_service_start = booking_data.get("endAt")
    if isinstance(next_service_start, datetime):
        current_bucket = datetime.now(BANGKOK).replace(second=0, microsecond=0)
        if current_bucket.minute % 15:
            current_bucket += timedelta(minutes=15 - current_bucket.minute % 15)
        next_service_start = max(next_service_start.astimezone(BANGKOK), current_bucket)
    response = {
        **serialize_booking(booking_snapshot),
        "participants": participants,
        "serviceItems": service_items,
        "nextServiceStartLocal": (
            next_service_start.isoformat() if isinstance(next_service_start, datetime) else None
        ),
    }
    if booking_data.get("adminEntryMode") == "HISTORICAL_RECORD":
        response["historicalVoid"] = FirestoreHistoricalCorrectionRepository(client).inspect(
            booking_id,
            branch_ids=_actor_branch_ids(actor),
        ).as_dict()
    return response


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


@router.post("/api/v1/admin/bookings/{booking_id}/services")
async def add_admin_booking_service(
    booking_id: str,
    request: AddBookingServiceRequest,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    if request.discount_amount_satang is not None and actor.get("role") != "ADMIN":
        raise PermissionDenied("Only ADMIN may change a booking discount")
    if request.discount_amount_satang is None and request.discount_reason is not None:
        raise ValidationDomainError("Discount amount is required with a discount reason")
    try:
        start_at = datetime.fromisoformat(f"{request.date}T{request.time}:00").replace(
            tzinfo=BANGKOK
        )
    except ValueError as error:
        raise ValidationDomainError("Invalid additional service date or time") from error
    if start_at.minute % get_settings().capacity_bucket_minutes:
        raise ValidationDomainError("Additional service time must align to 15 minutes")

    service, variant = _variant(client, request.service_variant_id)
    if variant.pricing_mode != "PER_PARTICIPANT" or variant.required_pax != 1:
        raise ValidationDomainError(
            "Only single-participant services may be added to an active Booking"
        )
    end_at = start_at + timedelta(minutes=variant.duration_minutes)
    bucket_starts = required_bucket_starts(start_at, variant.duration_minutes, 0)
    command_digest = hashlib.sha256(
        json.dumps(
            {
                "bookingId": booking_id,
                "action": "ADD_SERVICE",
                "request": request.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    matches = list(
        client.collection("bookings").where("publicBookingId", "==", booking_id).limit(1).stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking not found")
    booking_ref = matches[0].reference
    participant_ref = client.collection("booking_participants").document(request.participant_id)
    therapist_ref = client.collection("therapists").document(request.therapist_id)
    branch_id = str((matches[0].to_dict() or {}).get("branchId", "branch_001"))
    branch_ref = client.collection("branches").document(branch_id)
    bucket_refs = [
        client.collection("capacity_buckets").document(_bucket_id(branch_id, value))
        for value in bucket_starts
    ]
    line_ref = client.collection("booking_line_items").document()
    command_ref = client.collection("admin_commands").document(
        hashlib.sha256(request.command_id.encode()).hexdigest()
    )
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        command_snapshot = command_ref.get(transaction=tx)
        if command_snapshot.exists:
            command = command_snapshot.to_dict() or {}
            if (
                command.get("bookingDocId") != booking_ref.id
                or command.get("action") != "ADD_SERVICE"
                or command.get("requestDigest") != command_digest
            ):
                raise ConflictDomainError("Command ID was already used with different booking data")
            response = command.get("response")
            if not isinstance(response, dict):
                raise ConflictDomainError("Stored command response is unavailable")
            return response

        booking_snapshot = booking_ref.get(transaction=tx)
        booking = booking_snapshot.to_dict() or {}
        participant_snapshot = participant_ref.get(transaction=tx)
        participant = participant_snapshot.to_dict() or {}
        therapist_snapshot = therapist_ref.get(transaction=tx)
        therapist = therapist_snapshot.to_dict() or {}
        branch_snapshot = branch_ref.get(transaction=tx)
        branch = branch_snapshot.to_dict() or {}
        line_snapshots = list(
            client.collection("booking_line_items")
            .where("bookingDocId", "==", booking_ref.id)
            .stream(transaction=tx)
        )
        closure_snapshots = list(
            client.collection("special_closures")
            .where("branchId", "==", branch_id)
            .where("localDate", "==", request.date)
            .limit(1)
            .stream(transaction=tx)
        )
        bucket_snapshots = [ref.get(transaction=tx) for ref in bucket_refs]

        if int(booking.get("version", 1)) != request.expected_version:
            raise ConflictDomainError("Booking changed; reload before trying again")
        if booking.get("status") != BookingStatus.IN_SERVICE.value:
            raise ValidationDomainError(
                "Services may only be added while the Booking is in service"
            )
        if booking.get("capacityReleased"):
            raise ValidationDomainError("Booking capacity has already been released")
        if not participant_snapshot.exists or participant.get("bookingDocId") != booking_ref.id:
            raise ValidationDomainError("Booking participant is invalid")
        if (
            not therapist_snapshot.exists
            or not therapist.get("active")
            or (therapist.get("branchId") and therapist.get("branchId") != branch_id)
        ):
            raise ValidationDomainError(
                "The selected therapist must be active in the Booking branch"
            )
        if not branch_snapshot.exists:
            raise ValidationDomainError("Branch is not configured")
        if closure_snapshots:
            raise CapacityUnavailable("The branch is closed on the selected date")

        now = _utc_now()
        _validate_walk_in_window(
            start_at,
            now=now,
            bucket_minutes=get_settings().capacity_bucket_minutes,
        )
        _validate_operating_hours(start_at, variant.duration_minutes, branch)
        current_end_at = booking.get("endAt")
        if not isinstance(current_end_at, datetime):
            raise ValidationDomainError("Booking end time is unavailable")
        if start_at < current_end_at.astimezone(BANGKOK):
            raise ValidationDomainError(
                "Additional service must start after the current Booking schedule"
            )

        capacity = int(branch.get("activeCapacityUnits", branch.get("capacityUnits", 0)))
        if capacity <= 0:
            raise ValidationDomainError("Branch resource configuration is incomplete")
        for snapshot in bucket_snapshots:
            used = int((snapshot.to_dict() or {}).get("usedUnits", 0)) if snapshot.exists else 0
            if used + 1 > capacity:
                raise CapacityUnavailable(
                    "No capacity is available for the additional service duration"
                )

        old_subtotal = int(
            booking.get(
                "subtotalAmountSatang",
                int(booking.get("estimatedAmountSatang", 0))
                + int(booking.get("discountAmountSatang", 0)),
            )
        )
        new_subtotal = old_subtotal + int(variant.price_satang)
        old_discount = int(booking.get("discountAmountSatang", 0))
        old_discount_reason = str(booking.get("discountReason") or "") or None
        discount = old_discount
        discount_reason = old_discount_reason
        discount_audit_reason: str | None = None
        discount_changed = False
        if request.discount_amount_satang is not None:
            discount = request.discount_amount_satang
            requested_reason = (request.discount_reason or "").strip()
            reason_changed = bool(
                discount > 0
                and request.discount_reason is not None
                and requested_reason != (old_discount_reason or "")
            )
            discount_changed = discount != old_discount or reason_changed
            if discount_changed:
                discount_audit_reason = validate_fixed_discount(
                    subtotal_amount_satang=new_subtotal,
                    discount_amount_satang=discount,
                    reason=request.discount_reason,
                )
                discount_reason = discount_audit_reason if discount > 0 else None
            elif discount == 0 and requested_reason:
                raise ValidationDomainError("Discount reason requires a discount amount")

        net_amount = new_subtotal - discount
        tip_amount = int(booking.get("tipAmountSatang", 0))
        gross_amount = net_amount + tip_amount
        next_version = request.expected_version + 1
        therapist_name = str(therapist.get("displayName") or request.therapist_id)
        sequence = (
            max(
                [
                    int((snapshot.to_dict() or {}).get("sequence", index + 1))
                    for index, snapshot in enumerate(line_snapshots)
                ],
                default=0,
            )
            + 1
        )
        added_service = {
            "lineItemId": line_ref.id,
            "participantId": participant_ref.id,
            "participantName": participant.get("nickname") or "Guest",
            "sequence": sequence,
            "source": "ADMIN_ADD_ON",
            "serviceId": service.id,
            "variantId": variant.id,
            "serviceNameTh": service.name_th,
            "serviceNameEn": service.name_en,
            "durationMinutes": int(variant.duration_minutes),
            "lineTotalSatang": int(variant.price_satang),
            "therapistId": request.therapist_id,
            "therapistName": therapist_name,
            "scheduledStartAt": start_at.isoformat(),
            "scheduledEndAt": end_at.isoformat(),
        }
        response: dict[str, object] = {
            "bookingId": booking_id,
            "status": BookingStatus.IN_SERVICE.value,
            "version": next_version,
            "subtotalAmountSatang": new_subtotal,
            "discountAmountSatang": discount,
            "discountReason": discount_reason,
            "estimatedAmountSatang": net_amount,
            "tipAmountSatang": tip_amount,
            "grossAmountSatang": gross_amount,
            "endAt": end_at.isoformat(),
            "nextServiceStartLocal": end_at.isoformat(),
            "addedService": added_service,
        }

        reservation = booking.get("capacityReservation")
        reservation_data = dict(reservation) if isinstance(reservation, dict) else {}
        additions = list(reservation_data.get("additions") or [])
        additions.append(
            {
                "lineItemId": line_ref.id,
                "bucketIds": [ref.id for ref in bucket_refs],
                "units": 1,
            }
        )
        reservation_data["additions"] = additions
        service_names_th = list(booking.get("serviceNamesTh") or [])
        service_names_en = list(booking.get("serviceNamesEn") or [])
        service_names_th.append(service.name_th)
        service_names_en.append(service.name_en)
        booking_update: dict[str, object] = {
            "serviceNamesTh": service_names_th,
            "serviceNamesEn": service_names_en,
            "endAt": end_at,
            "subtotalAmountSatang": new_subtotal,
            "discountAmountSatang": discount,
            "discountReason": discount_reason,
            "estimatedAmountSatang": net_amount,
            "grossAmountSatang": gross_amount,
            "capacityReservation": reservation_data,
            "version": next_version,
            "updatedAt": now,
        }
        if discount_changed:
            booking_update.update(
                {
                    "discountType": "ADMIN_FIXED" if discount > 0 else None,
                    "discountAppliedBy": actor["uid"] if discount > 0 else None,
                    "discountAppliedAt": now if discount > 0 else None,
                }
            )

        tx.set(
            line_ref,
            {
                "bookingDocId": booking_ref.id,
                "branchId": branch_id,
                "sequence": sequence,
                "source": "ADMIN_ADD_ON",
                "serviceSnapshot": {
                    "serviceId": service.id,
                    "variantId": variant.id,
                    "nameTh": service.name_th,
                    "nameEn": service.name_en,
                    "durationMinutes": int(variant.duration_minutes),
                    "pricingMode": variant.pricing_mode,
                    "requiredPax": int(variant.required_pax),
                    "unitPriceSatang": int(variant.price_satang),
                },
                "quantity": 1,
                "lineTotalSatang": int(variant.price_satang),
                "financiallyExcluded": False,
                "participantIds": [participant_ref.id],
                "assignment": {
                    "therapistId": request.therapist_id,
                    "therapistName": therapist_name,
                    "assignedAt": now,
                    "assignedBy": actor["uid"],
                },
                "scheduledStartAt": start_at,
                "scheduledEndAt": end_at,
                "createdAt": now,
                "createdBy": actor["uid"],
            },
        )
        tx.update(booking_ref, booking_update)
        for ref, snapshot, bucket_start in zip(
            bucket_refs, bucket_snapshots, bucket_starts, strict=True
        ):
            used = int((snapshot.to_dict() or {}).get("usedUnits", 0)) if snapshot.exists else 0
            tx.set(
                ref,
                {
                    "branchId": branch_id,
                    "bucketStart": bucket_start,
                    "usedUnits": used + 1,
                    "capacityUnits": capacity,
                    "updatedAt": now,
                },
                merge=True,
            )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "BOOKING_SERVICE_ADDED",
                "bookingDocId": booking_ref.id,
                "publicBookingId": booking_id,
                "bookingLineItemId": line_ref.id,
                "participantId": participant_ref.id,
                "serviceId": service.id,
                "variantId": variant.id,
                "therapistId": request.therapist_id,
                "lineTotalSatang": int(variant.price_satang),
                "oldSubtotalAmountSatang": old_subtotal,
                "newSubtotalAmountSatang": new_subtotal,
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "actorRole": actor.get("role"),
                "commandId": request.command_id,
                "createdAt": now,
            },
        )
        if discount_changed:
            event_type = (
                "BOOKING_DISCOUNT_APPLIED"
                if old_discount == 0 and discount > 0
                else "BOOKING_DISCOUNT_REMOVED"
                if old_discount > 0 and discount == 0
                else "BOOKING_DISCOUNT_UPDATED"
            )
            tx.set(
                client.collection("audit_events").document(),
                {
                    "eventType": event_type,
                    "bookingDocId": booking_ref.id,
                    "publicBookingId": booking_id,
                    "actorType": "ADMIN_USER",
                    "actorId": actor["uid"],
                    "actorRole": actor.get("role"),
                    "oldDiscountAmountSatang": old_discount,
                    "newDiscountAmountSatang": discount,
                    "oldDiscountReason": old_discount_reason,
                    "discountReason": discount_audit_reason,
                    "oldServiceAmountSatang": int(
                        booking.get("estimatedAmountSatang", old_subtotal - old_discount)
                    ),
                    "newServiceAmountSatang": net_amount,
                    "bookingVersion": next_version,
                    "commandId": request.command_id,
                    "occurredAt": now,
                    "createdAt": now,
                },
            )
        tx.set(
            command_ref,
            {
                "bookingDocId": booking_ref.id,
                "action": "ADD_SERVICE",
                "requestDigest": command_digest,
                "response": response,
                "createdAt": now,
            },
        )
        return response

    return write(transaction)


@router.post("/api/v1/admin/bookings/{booking_id}:void-historical")
async def void_admin_historical_booking(
    booking_id: str,
    request: VoidHistoricalBookingRequest,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    if actor.get("role") != "ADMIN":
        raise PermissionDenied("Only ADMIN may void a paid historical Booking")
    return FirestoreHistoricalCorrectionRepository(client).void(
        booking_id,
        branch_ids=_actor_branch_ids(actor),
        actor_uid=str(actor["uid"]),
        expected_version=request.expected_version,
        command_id=request.command_id,
        reason=request.reason,
    )


@router.post("/api/v1/admin/bookings/{booking_id}:{action}")
async def transition_admin_booking(
    booking_id: str,
    action: str,
    request: TransitionRequest,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    normalized_action = action.upper()
    discount_fields_supplied = (
        request.discount_amount_satang is not None or request.discount_reason is not None
    )
    if discount_fields_supplied and normalized_action != "START":
        raise ValidationDomainError("Discount may only be supplied when service starts")
    if (
        normalized_action == "START"
        and request.discount_amount_satang is None
        and request.discount_reason is not None
    ):
        raise ValidationDomainError("Discount amount is required with a discount reason")
    if request.discount_amount_satang is not None and actor.get("role") != "ADMIN":
        raise PermissionDenied("Only ADMIN may change a booking discount")
    command_digest = hashlib.sha256(
        json.dumps(
            {
                "bookingId": booking_id,
                "action": normalized_action,
                "request": request.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

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
            command = command_snapshot.to_dict() or {}
            if (
                command.get("bookingDocId") != booking_ref.id
                or command.get("action") != normalized_action
                or command.get("requestDigest") != command_digest
            ):
                raise ConflictDomainError("Command ID was already used with different booking data")
            return {
                "status": str(command.get("status", data.get("status"))),
                "version": int(command.get("version", data.get("version", 1))),
                "subtotalAmountSatang": int(
                    command.get(
                        "subtotalAmountSatang",
                        data.get(
                            "subtotalAmountSatang",
                            int(data.get("estimatedAmountSatang", 0))
                            + int(data.get("discountAmountSatang", 0)),
                        ),
                    )
                ),
                "discountAmountSatang": int(
                    command.get("discountAmountSatang", data.get("discountAmountSatang", 0))
                ),
                "discountReason": command.get("discountReason", data.get("discountReason")),
                "estimatedAmountSatang": int(
                    command.get("estimatedAmountSatang", data.get("estimatedAmountSatang", 0))
                ),
                "tipAmountSatang": int(
                    command.get("tipAmountSatang", data.get("tipAmountSatang", 0))
                ),
                "grossAmountSatang": int(
                    command.get(
                        "grossAmountSatang",
                        int(data.get("estimatedAmountSatang", 0))
                        + int(data.get("tipAmountSatang", 0)),
                    )
                ),
            }
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
            normalized_action,
            cancellation_reason=request.reason,
            all_therapists_assigned=data.get("assignmentState") == "ASSIGNED",
            no_show_window_reached=no_show_reached,
        )
        if (
            target is BookingStatus.CANCELLED
            and current is BookingStatus.RECORDED
            and data.get("paymentStatus") == "PAID"
        ):
            raise HistoricalCorrectionRequired(
                "Paid historical Booking requires the financial correction action"
            )
        subtotal_amount_satang = int(
            data.get(
                "subtotalAmountSatang",
                int(data.get("estimatedAmountSatang", 0))
                + int(data.get("discountAmountSatang", 0)),
            )
        )
        old_discount_amount_satang = int(data.get("discountAmountSatang", 0))
        old_discount_reason = str(data.get("discountReason") or "") or None
        discount_amount_satang = old_discount_amount_satang
        discount_reason = old_discount_reason
        discount_audit_reason: str | None = None
        discount_changed = False
        if target is BookingStatus.IN_SERVICE and request.discount_amount_satang is not None:
            requested_reason = (request.discount_reason or "").strip()
            discount_amount_satang = request.discount_amount_satang
            reason_changed = bool(
                discount_amount_satang > 0
                and request.discount_reason is not None
                and requested_reason != (old_discount_reason or "")
            )
            discount_changed = (
                discount_amount_satang != old_discount_amount_satang or reason_changed
            )
            if discount_changed:
                discount_audit_reason = validate_fixed_discount(
                    subtotal_amount_satang=subtotal_amount_satang,
                    discount_amount_satang=discount_amount_satang,
                    reason=request.discount_reason,
                )
                discount_reason = discount_audit_reason if discount_amount_satang > 0 else None
            elif discount_amount_satang == 0 and requested_reason:
                raise ValidationDomainError("Discount reason requires a discount amount")

        estimated_amount_satang = subtotal_amount_satang - discount_amount_satang
        tip_amount_satang = int(data.get("tipAmountSatang", 0))
        gross_amount_satang = estimated_amount_satang + tip_amount_satang
        next_version = int(data.get("version", 1)) + 1
        update: dict[str, object] = {
            "status": target.value,
            "customerListBucket": customer_list_bucket(target.value),
            "version": next_version,
            "updatedAt": now,
        }
        if target is BookingStatus.IN_SERVICE:
            update["serviceStartedAt"] = now
            if discount_changed:
                update.update(
                    {
                        "subtotalAmountSatang": subtotal_amount_satang,
                        "discountAmountSatang": discount_amount_satang,
                        "discountType": ("ADMIN_FIXED" if discount_amount_satang > 0 else None),
                        "discountReason": discount_reason,
                        "discountAppliedBy": (actor["uid"] if discount_amount_satang > 0 else None),
                        "discountAppliedAt": now if discount_amount_satang > 0 else None,
                        "estimatedAmountSatang": estimated_amount_satang,
                        "grossAmountSatang": gross_amount_satang,
                    }
                )
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
            bucket_units: dict[str, int] = {}
            exact_bucket_units = reservation.get("bucketUnits", [])
            if isinstance(exact_bucket_units, list) and exact_bucket_units:
                for item in exact_bucket_units:
                    if not isinstance(item, dict):
                        continue
                    bucket_id = str(item.get("bucketId") or "")
                    if not bucket_id:
                        continue
                    bucket_units[bucket_id] = bucket_units.get(bucket_id, 0) + int(
                        item.get("units", 0)
                    )
            else:
                legacy_units = int(reservation.get("units", data.get("pax", 1)))
                for bucket_id in reservation.get("bucketIds", []):
                    bucket_units[str(bucket_id)] = (
                        bucket_units.get(str(bucket_id), 0) + legacy_units
                    )
            for addition in reservation.get("additions", []):
                if not isinstance(addition, dict):
                    continue
                addition_units = int(addition.get("units", 1))
                for bucket_id in addition.get("bucketIds", []):
                    bucket_units[str(bucket_id)] = (
                        bucket_units.get(str(bucket_id), 0) + addition_units
                    )
            bucket_refs = [
                client.collection("capacity_buckets").document(bucket_id)
                for bucket_id in bucket_units
            ]
            bucket_snapshots = [ref.get(transaction=tx) for ref in bucket_refs]
            update["capacityReleased"] = True
            for bucket_ref, bucket_snapshot in zip(bucket_refs, bucket_snapshots, strict=True):
                bucket = bucket_snapshot.to_dict() or {}
                tx.set(
                    bucket_ref,
                    {
                        "usedUnits": max(
                            0,
                            int(bucket.get("usedUnits", 0)) - bucket_units[bucket_ref.id],
                        ),
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
        if discount_changed:
            discount_event_type = (
                "BOOKING_DISCOUNT_APPLIED"
                if old_discount_amount_satang == 0 and discount_amount_satang > 0
                else "BOOKING_DISCOUNT_REMOVED"
                if old_discount_amount_satang > 0 and discount_amount_satang == 0
                else "BOOKING_DISCOUNT_UPDATED"
            )
            tx.set(
                client.collection("audit_events").document(),
                {
                    "eventType": discount_event_type,
                    "actorType": "ADMIN_USER",
                    "actorId": actor["uid"],
                    "actorRole": actor.get("role"),
                    "branchId": data.get("branchId"),
                    "bookingDocId": booking_ref.id,
                    "publicBookingId": booking_id,
                    "subtotalAmountSatang": subtotal_amount_satang,
                    "oldDiscountAmountSatang": old_discount_amount_satang,
                    "newDiscountAmountSatang": discount_amount_satang,
                    "oldDiscountReason": old_discount_reason,
                    "discountReason": discount_audit_reason,
                    "oldServiceAmountSatang": int(
                        data.get(
                            "estimatedAmountSatang",
                            subtotal_amount_satang - old_discount_amount_satang,
                        )
                    ),
                    "newServiceAmountSatang": estimated_amount_satang,
                    "bookingVersion": next_version,
                    "commandId": request.command_id,
                    "occurredAt": now,
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
        response = {
            "status": target.value,
            "version": next_version,
            "subtotalAmountSatang": subtotal_amount_satang,
            "discountAmountSatang": discount_amount_satang,
            "discountReason": discount_reason,
            "estimatedAmountSatang": estimated_amount_satang,
            "tipAmountSatang": tip_amount_satang,
            "grossAmountSatang": gross_amount_satang,
        }
        tx.set(
            command_ref,
            {
                "bookingDocId": booking_ref.id,
                "action": normalized_action,
                "requestDigest": command_digest,
                **response,
                "createdAt": now,
            },
        )
        return response

    return {"bookingId": booking_id, **write(transaction)}
