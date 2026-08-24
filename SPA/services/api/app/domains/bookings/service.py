from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from datetime import date as calendar_date
from secrets import token_urlsafe
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.errors import (
    ActivePendingLimit,
    AdvanceWindowViolation,
    CapacityUnavailable,
    DuplicateBooking,
    IdempotencyConflict,
    ValidationDomainError,
)
from app.core.settings import get_settings
from app.domains.capacity.buckets import required_bucket_starts
from app.domains.catalog.seed import load_catalog_manifest
from app.domains.customers.phone import mask_phone, normalize_thai_phone

BRANCH_TIMEZONE = ZoneInfo("Asia/Bangkok")


def _validate_advance_window(
    start_at: datetime,
    branch: dict[str, object],
    *,
    today: calendar_date | None = None,
) -> None:
    booking_window = branch.get("bookingWindow") or {}
    if not isinstance(booking_window, dict):
        booking_window = {}
    min_days = max(0, int(booking_window.get("minDays", 1)))
    max_days = max(min_days, int(booking_window.get("maxDays", 30)))
    branch_today = today or datetime.now(BRANCH_TIMEZONE).date()
    days_ahead = (start_at.astimezone(BRANCH_TIMEZONE).date() - branch_today).days
    if days_ahead < min_days or days_ahead > max_days:
        raise AdvanceWindowViolation(
            f"Bookings must be made {min_days} to {max_days} local calendar days in advance"
        )


def _variant(client: firestore.Client, variant_id: str):
    for snapshot in client.collection("services").where("active", "==", True).stream():
        service = snapshot.to_dict() or {}
        for variant in service.get("variants", []):
            if variant.get("variantId") == variant_id and variant.get("active", True):
                return SimpleNamespace(
                    id=service.get("serviceId", snapshot.id),
                    name_th=service.get("nameTh", ""),
                    name_en=service.get("nameEn", ""),
                ), SimpleNamespace(
                    id=variant_id,
                    duration_minutes=int(variant["durationMinutes"]),
                    price_satang=int(variant["priceSatang"]),
                    pricing_mode=variant["pricingMode"],
                    required_pax=int(variant["requiredPax"]),
                )
    for service in load_catalog_manifest().services:
        for variant in service.variants:
            if variant.id == variant_id and service.active and variant.active:
                return service, variant
    raise ValidationDomainError("Unknown or inactive service variant")


def _request_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _bucket_id(branch_id: str, bucket_start: datetime) -> str:
    local = bucket_start.astimezone(BRANCH_TIMEZONE)
    return f"{branch_id}_{local:%Y%m%d_%H%M}"


def create_booking(
    client: firestore.Client,
    *,
    branch_id: str,
    date: str,
    time: str,
    phone: str,
    participants: list[dict[str, object]],
    idempotency_key: str | None,
    line_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = get_settings()
    if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
        raise ValidationDomainError("Idempotency-Key is required")
    if len(participants) not in {1, 2}:
        raise ValidationDomainError("A booking must contain one or two participants")
    try:
        start_at = datetime.fromisoformat(f"{date}T{time}:00").replace(tzinfo=BRANCH_TIMEZONE)
    except ValueError as error:
        raise ValidationDomainError("Invalid booking date or time") from error
    if start_at.minute % settings.capacity_bucket_minutes:
        raise ValidationDomainError("Booking time must align to a 15-minute interval")

    e164 = normalize_thai_phone(phone)
    selections = []
    for participant in participants:
        if not participant.get("healthConsent"):
            raise ValidationDomainError("Explicit health consent is required for every participant")
        service, variant = _variant(client, str(participant.get("serviceVariantId", "")))
        selections.append((participant, service, variant))
    required_two = [variant.id for _, _, variant in selections if variant.required_pax == 2]
    if required_two and (len(selections) != 2 or len(set(required_two)) != 1):
        raise ValidationDomainError("A two-person package must be selected for both participants")

    max_duration = max(variant.duration_minutes for _, _, variant in selections)
    if start_at + timedelta(minutes=max_duration) > datetime.combine(
        start_at.date(), datetime.strptime("22:00", "%H:%M").time(), BRANCH_TIMEZONE
    ):
        raise ValidationDomainError("The selected service ends after branch closing time")

    request_payload: dict[str, object] = {
        "branchId": branch_id,
        "date": date,
        "time": time,
        "phone": e164,
        "participants": participants,
        "lineUserIdHash": (
            hashlib.sha256(str(line_identity["sub"]).encode()).hexdigest()
            if line_identity and line_identity.get("sub")
            else None
        ),
    }
    digest = _request_hash(request_payload)
    idem_ref = client.collection("booking_idempotency").document(
        hashlib.sha256(idempotency_key.encode()).hexdigest()
    )
    branch_ref = client.collection("branches").document(branch_id)
    booking_ref = client.collection("bookings").document()
    public_id = f"BK-{date.replace('-', '')}-{uuid4().hex[:6].upper()}"
    now = datetime.now(UTC)
    bucket_starts = required_bucket_starts(start_at, max_duration, 0)
    bucket_refs = [
        client.collection("capacity_buckets").document(_bucket_id(branch_id, item))
        for item in bucket_starts
    ]
    total = sum(
        variant.price_satang
        for index, (_, _, variant) in enumerate(selections)
        if variant.pricing_mode == "PER_PARTICIPANT" or index == 0
    )
    status_token = token_urlsafe(32)
    status_token_hash = hashlib.sha256(status_token.encode()).hexdigest()
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction):
        idem_snapshot = idem_ref.get(transaction=tx)
        if idem_snapshot.exists:
            existing = idem_snapshot.to_dict() or {}
            if existing.get("requestHash") != digest:
                raise IdempotencyConflict("Idempotency-Key was already used with different data")
            return {
                "bookingId": existing["publicBookingId"],
                "status": existing["status"],
                "statusToken": existing["statusToken"],
                "estimatedAmountSatang": existing["estimatedAmountSatang"],
                "idempotentReplay": True,
            }

        branch_snapshot = branch_ref.get(transaction=tx)
        if not branch_snapshot.exists:
            raise ValidationDomainError("Branch is not configured")
        branch = branch_snapshot.to_dict() or {}
        _validate_advance_window(start_at, branch)
        capacity = int(branch.get("activeCapacityUnits", branch.get("capacityUnits", 0)))
        if capacity <= 0:
            raise ValidationDomainError("Branch resource configuration is incomplete")
        closure_refs = list(
            client.collection("special_closures")
            .where("branchId", "==", branch_id)
            .where("localDate", "==", date)
            .stream(transaction=tx)
        )
        if closure_refs:
            raise CapacityUnavailable("The branch is closed on the selected date")

        pending = list(
            client.collection("bookings")
            .where("branchId", "==", branch_id)
            .where("contact.phoneE164", "==", e164)
            .where("status", "==", "PENDING")
            .limit(3)
            .stream(transaction=tx)
        )
        if any((item.to_dict() or {}).get("startAt") == start_at for item in pending):
            raise DuplicateBooking("An active booking already exists for this phone and time")
        if len(pending) >= 2:
            raise ActivePendingLimit("This phone already has two active pending bookings")

        bucket_snapshots = [ref.get(transaction=tx) for ref in bucket_refs]
        units = len(selections)
        for snapshot in bucket_snapshots:
            used = int((snapshot.to_dict() or {}).get("usedUnits", 0)) if snapshot.exists else 0
            if used + units > capacity:
                raise CapacityUnavailable(
                    "No capacity is available for the complete service duration"
                )

        result = {
            "bookingId": public_id,
            "status": "PENDING",
            "statusToken": status_token,
            "estimatedAmountSatang": total,
            "idempotentReplay": False,
        }
        booking_data = {
            "publicBookingId": public_id,
            "branchId": branch_id,
            "source": "LINE_CUSTOMER" if line_identity else "GUEST_WEB",
            "status": "PENDING",
            "contact": {"phoneMasked": mask_phone(e164), "phoneE164": e164},
            "customerName": str(selections[0][0].get("nickname", "Guest")),
            "serviceName": selections[0][1].name_en,
            "serviceId": selections[0][1].id,
            "serviceNameTh": selections[0][1].name_th,
            "serviceNameEn": selections[0][1].name_en,
            "startAt": start_at,
            "endAt": start_at + timedelta(minutes=max_duration),
            "localDate": date,
            "localStartTime": time,
            "timezone": "Asia/Bangkok",
            "pax": len(selections),
            "estimatedAmountSatang": total,
            "priceIncludesVat": True,
            "healthAlert": any(bool(p.get("hasHealthInformation")) for p, _, _ in selections),
            "assignmentState": "UNASSIGNED",
            "capacityReleased": False,
            "capacityReservation": {"bucketIds": [ref.id for ref in bucket_refs], "units": units},
            "version": 1,
            "createdAt": now,
            "updatedAt": now,
            "statusTokenHash": status_token_hash,
        }
        tx.set(booking_ref, booking_data)
        if line_identity:
            line_user_id = str(line_identity["sub"])
            line_link_ref = client.collection("line_booking_links").document(booking_ref.id)
            tx.set(
                line_link_ref,
                {
                    "bookingDocId": booking_ref.id,
                    "lineUserId": line_user_id,
                    "channelId": str(line_identity.get("aud", "")),
                    "verifiedAt": now,
                    "linkedAt": now,
                    "active": True,
                    "version": 1,
                },
            )
            audit_ref = client.collection("audit_events").document()
            tx.set(
                audit_ref,
                {
                    "eventType": "BOOKING_LINE_LINKED",
                    "bookingDocId": booking_ref.id,
                    "publicBookingId": public_id,
                    "actorType": "LINE_CUSTOMER",
                    "actorIdHash": hashlib.sha256(line_user_id.encode()).hexdigest(),
                    "createdAt": now,
                },
            )
        for ref, snapshot, bucket_start in zip(
            bucket_refs, bucket_snapshots, bucket_starts, strict=True
        ):
            used = int((snapshot.to_dict() or {}).get("usedUnits", 0)) if snapshot.exists else 0
            tx.set(
                ref,
                {
                    "branchId": branch_id,
                    "bucketStart": bucket_start,
                    "usedUnits": used + units,
                    "capacityUnits": capacity,
                    "updatedAt": now,
                },
                merge=True,
            )

        participant_ids: list[str] = []
        for index, (participant, service, variant) in enumerate(selections, start=1):
            participant_ref = client.collection("booking_participants").document()
            participant_ids.append(participant_ref.id)
            line_ref = client.collection("booking_line_items").document()
            health_ref = client.collection("health_profiles").document()
            consent_ref = client.collection("consent_evidence").document()
            tx.set(
                line_ref,
                {
                    "bookingDocId": booking_ref.id,
                    "branchId": branch_id,
                    "serviceSnapshot": {
                        "serviceId": service.id,
                        "variantId": variant.id,
                        "nameTh": service.name_th,
                        "nameEn": service.name_en,
                        "durationMinutes": variant.duration_minutes,
                        "pricingMode": variant.pricing_mode,
                        "requiredPax": variant.required_pax,
                        "unitPriceSatang": variant.price_satang,
                    },
                    "quantity": 1,
                    "lineTotalSatang": variant.price_satang
                    if variant.pricing_mode == "PER_PARTICIPANT" or index == 1
                    else 0,
                    "participantIds": [participant_ref.id],
                    "createdAt": now,
                },
            )
            tx.set(
                participant_ref,
                {
                    "bookingDocId": booking_ref.id,
                    "branchId": branch_id,
                    "sequence": index,
                    "nickname": str(participant.get("nickname", "")),
                    "healthAlert": bool(participant.get("hasHealthInformation")),
                    "healthProfileId": health_ref.id,
                    "createdAt": now,
                },
            )
            tx.set(
                health_ref,
                {
                    "bookingDocId": booking_ref.id,
                    "participantId": participant_ref.id,
                    "hasInformation": bool(participant.get("hasHealthInformation")),
                    "details": str(participant.get("healthDetails") or ""),
                    "policyVersion": settings.health_retention_policy_version,
                    "retentionUntil": now + timedelta(days=365 * settings.health_retention_years),
                    "createdAt": now,
                    "updatedAt": now,
                },
            )
            tx.set(
                consent_ref,
                {
                    "bookingDocId": booking_ref.id,
                    "participantId": participant_ref.id,
                    "purpose": "HEALTH_DATA_EXPLICIT",
                    "accepted": True,
                    "version": settings.health_consent_version,
                    "acceptedAt": now,
                },
            )

        event_ref = client.collection("notification_outbox").document()
        tx.set(
            event_ref,
            {
                "eventId": event_ref.id,
                "eventType": "BOOKING_CREATED",
                "aggregateId": booking_ref.id,
                "publicBookingId": public_id,
                "state": "PENDING",
                "enqueueGeneration": 0,
                "createdAt": now,
                "updatedAt": now,
            },
        )
        if line_identity:
            pending_ack_ref = client.collection("notification_outbox").document()
            tx.set(
                pending_ack_ref,
                {
                    "eventId": pending_ack_ref.id,
                    "eventType": "BOOKING_PENDING_ACKNOWLEDGEMENT",
                    "aggregateId": booking_ref.id,
                    "publicBookingId": public_id,
                    "state": "PENDING",
                    "enqueueGeneration": 0,
                    "createdAt": now,
                    "updatedAt": now,
                },
            )
        tx.set(
            idem_ref,
            {
                "requestHash": digest,
                "publicBookingId": public_id,
                "status": "PENDING",
                "statusToken": status_token,
                "estimatedAmountSatang": total,
                "bookingDocId": booking_ref.id,
                "expiresAt": now + timedelta(hours=24),
                "createdAt": now,
            },
        )
        return result

    return write(transaction)


def serialize_booking(snapshot: firestore.DocumentSnapshot) -> dict[str, object]:
    data = snapshot.to_dict() or {}
    start_at = data.get("startAt")
    end_at = data.get("endAt")
    if isinstance(start_at, datetime):
        data["startAt"] = start_at.isoformat()
    if isinstance(end_at, datetime):
        data["endAt"] = end_at.isoformat()
    for protected in ("statusToken", "statusTokenHash", "idempotencyKey", "capacityReservation"):
        data.pop(protected, None)
    data["bookingId"] = data.pop("publicBookingId", snapshot.id)
    contact = data.pop("contact", {}) or {}
    data["customerPhoneMasked"] = contact.get("phoneMasked", "")
    data["startLocal"] = data.get("startAt")
    data["durationMinutes"] = (
        int((end_at - start_at).total_seconds() // 60)
        if isinstance(end_at, datetime) and isinstance(start_at, datetime)
        else 0
    )
    data.setdefault("therapistName", None)
    data.setdefault("healthAlert", False)
    return data
