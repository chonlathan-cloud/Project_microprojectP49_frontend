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
    PermissionDenied,
    ValidationDomainError,
)
from app.core.settings import get_settings
from app.domains.capacity.buckets import required_bucket_starts
from app.domains.catalog.seed import load_catalog_manifest
from app.domains.customers.phone import mask_phone, normalize_thai_phone
from app.integrations.line_identity import line_identity_hash

BRANCH_TIMEZONE = ZoneInfo("Asia/Bangkok")

UPCOMING_BOOKING_STATUSES = {"PENDING", "CONFIRMED", "IN_SERVICE"}


def customer_list_bucket(status: str) -> str:
    return "UPCOMING" if status in UPCOMING_BOOKING_STATUSES else "HISTORY"


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


def _validate_walk_in_window(
    start_at: datetime,
    *,
    now: datetime | None = None,
    bucket_minutes: int = 15,
) -> None:
    local_now = (now or datetime.now(UTC)).astimezone(BRANCH_TIMEZONE)
    current_bucket = local_now.replace(
        minute=(local_now.minute // bucket_minutes) * bucket_minutes,
        second=0,
        microsecond=0,
    )
    if start_at.date() != local_now.date():
        raise AdvanceWindowViolation("Walk-in bookings must be for the current branch-local date")
    if start_at < current_bucket:
        raise AdvanceWindowViolation("Walk-in booking time cannot be in the past")


def _validate_staff_assisted_window(
    start_at: datetime,
    *,
    now: datetime | None = None,
    bucket_minutes: int = 15,
) -> None:
    local_now = (now or datetime.now(UTC)).astimezone(BRANCH_TIMEZONE)
    current_bucket = local_now.replace(
        minute=(local_now.minute // bucket_minutes) * bucket_minutes,
        second=0,
        microsecond=0,
    )
    if start_at < current_bucket:
        raise AdvanceWindowViolation(
            "Staff-assisted bookings in the past must use HISTORICAL_RECORD"
        )


def _validate_historical_record_window(
    start_at: datetime,
    *,
    now: datetime | None = None,
    bucket_minutes: int = 15,
) -> None:
    local_now = (now or datetime.now(UTC)).astimezone(BRANCH_TIMEZONE)
    current_bucket = local_now.replace(
        minute=(local_now.minute // bucket_minutes) * bucket_minutes,
        second=0,
        microsecond=0,
    )
    if start_at >= current_bucket:
        raise AdvanceWindowViolation(
            "Historical records require an appointment time in the past"
        )


def _validate_operating_hours(
    start_at: datetime,
    duration_minutes: int,
    branch: dict[str, object],
) -> None:
    operating_hours = branch.get("operatingHours") or {}
    if not isinstance(operating_hours, dict):
        operating_hours = {}
    hours = operating_hours.get(str(start_at.weekday()), {"open": "10:00", "close": "22:00"})
    if not isinstance(hours, dict):
        hours = {"open": "10:00", "close": "22:00"}
    try:
        opens_at = datetime.combine(
            start_at.date(),
            datetime.strptime(str(hours.get("open", "10:00")), "%H:%M").time(),
            BRANCH_TIMEZONE,
        )
        closes_at = datetime.combine(
            start_at.date(),
            datetime.strptime(str(hours.get("close", "22:00")), "%H:%M").time(),
            BRANCH_TIMEZONE,
        )
    except ValueError as error:
        raise ValidationDomainError("Branch operating hours are invalid") from error
    if start_at < opens_at or start_at + timedelta(minutes=duration_minutes) > closes_at:
        raise ValidationDomainError("The selected service falls outside branch operating hours")


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
    phone: str | None,
    participants: list[dict[str, object]],
    idempotency_key: str | None,
    line_identity: dict[str, object] | None = None,
    source: str = "GUEST_WEB",
    initial_status: str = "PENDING",
    actor_id: str | None = None,
    admin_booking_mode: str | None = None,
    consent_capture_method: str = "SELF_SERVICE",
    booking_privacy_acknowledged: bool = False,
    actor_role: str | None = None,
    discount_amount_satang: int = 0,
    discount_reason: str | None = None,
    tip_amount_satang: int = 0,
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

    if source not in {"GUEST_WEB", "LINE_CUSTOMER", "ADMIN_WEB"}:
        raise ValidationDomainError("Unsupported booking source")
    if initial_status not in {"PENDING", "CONFIRMED", "RECORDED"}:
        raise ValidationDomainError("Unsupported initial booking status")
    historical_record = source == "ADMIN_WEB" and admin_booking_mode == "HISTORICAL_RECORD"
    if source == "ADMIN_WEB":
        if not actor_id:
            raise ValidationDomainError("Admin actor is required for staff-assisted booking")
        if admin_booking_mode not in {"WALK_IN", "STAFF_ASSISTED", "HISTORICAL_RECORD"}:
            raise ValidationDomainError("Unsupported Admin booking mode")
        expected_status = "RECORDED" if historical_record else "CONFIRMED"
        if initial_status != expected_status:
            raise ValidationDomainError(
                f"{admin_booking_mode} bookings must start {expected_status.lower()}"
            )
        if consent_capture_method not in {"VERBAL", "PAPER"}:
            raise ValidationDomainError(
                "Admin-entered consent must be captured verbally or on paper"
            )
        if not booking_privacy_acknowledged:
            raise ValidationDomainError("Booking privacy acknowledgement is required")
        if admin_booking_mode == "WALK_IN":
            _validate_walk_in_window(
                start_at,
                bucket_minutes=settings.capacity_bucket_minutes,
            )
        elif historical_record:
            _validate_historical_record_window(
                start_at,
                bucket_minutes=settings.capacity_bucket_minutes,
            )
        else:
            _validate_staff_assisted_window(
                start_at,
                bucket_minutes=settings.capacity_bucket_minutes,
            )
    elif initial_status != "PENDING":
        raise ValidationDomainError("Customer bookings must start pending")

    normalized_phone = (phone or "").strip()
    e164 = normalize_thai_phone(normalized_phone) if normalized_phone else None
    if source != "ADMIN_WEB" and not e164:
        raise ValidationDomainError("A valid Thai phone number is required")
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
    subtotal = sum(
        variant.price_satang
        for index, (_, _, variant) in enumerate(selections)
        if variant.pricing_mode == "PER_PARTICIPANT" or index == 0
    )
    normalized_discount_reason = (discount_reason or "").strip() or None
    if isinstance(discount_amount_satang, bool) or not isinstance(discount_amount_satang, int):
        raise ValidationDomainError("Discount amount must be integer satang")
    if discount_amount_satang < 0 or discount_amount_satang % 100:
        raise ValidationDomainError("Discount must be a non-negative whole-baht amount")
    if discount_amount_satang:
        if source != "ADMIN_WEB" or actor_role != "ADMIN":
            raise PermissionDenied("Only ADMIN may apply a booking discount")
        if not normalized_discount_reason:
            raise ValidationDomainError("Discount reason is required")
        if len(normalized_discount_reason) > 200:
            raise ValidationDomainError("Discount reason must not exceed 200 characters")
        if discount_amount_satang >= subtotal:
            raise ValidationDomainError("Discount must be less than the booking subtotal")
    elif normalized_discount_reason:
        raise ValidationDomainError("Discount reason requires a discount amount")
    if isinstance(tip_amount_satang, bool) or not isinstance(tip_amount_satang, int):
        raise ValidationDomainError("Tip amount must be integer satang")
    if tip_amount_satang < 0 or tip_amount_satang % 100:
        raise ValidationDomainError("Tip must be a non-negative whole-baht amount")
    if tip_amount_satang and not historical_record:
        raise ValidationDomainError("Tips may only be recorded for historical records")
    total = subtotal - discount_amount_satang
    gross_total = total + tip_amount_satang

    request_payload: dict[str, object] = {
        "branchId": branch_id,
        "date": date,
        "time": time,
        "phone": e164,
        "participants": participants,
        "source": source,
        "initialStatus": initial_status,
        "consentCaptureMethod": consent_capture_method,
        "bookingPrivacyAcknowledged": booking_privacy_acknowledged,
        "adminBookingMode": admin_booking_mode,
        "discountAmountSatang": discount_amount_satang,
        "discountReason": normalized_discount_reason,
        "tipAmountSatang": tip_amount_satang,
        "lineUserIdHash": (
            hashlib.sha256(str(line_identity["sub"]).encode()).hexdigest()
            if line_identity and line_identity.get("sub")
            else None
        ),
    }
    digest = _request_hash(request_payload)
    idempotency_scope = (
        f"ADMIN_WEB:{actor_id}:{idempotency_key}" if source == "ADMIN_WEB" else idempotency_key
    )
    idem_ref = client.collection("booking_idempotency").document(
        hashlib.sha256(str(idempotency_scope).encode()).hexdigest()
    )
    branch_ref = client.collection("branches").document(branch_id)
    booking_ref = client.collection("bookings").document()
    public_id = f"BK-{date.replace('-', '')}-{uuid4().hex[:6].upper()}"
    now = datetime.now(UTC)
    bucket_starts = (
        [] if historical_record else required_bucket_starts(start_at, max_duration, 0)
    )
    bucket_refs = [
        client.collection("capacity_buckets").document(_bucket_id(branch_id, item))
        for item in bucket_starts
    ]
    status_token = token_urlsafe(32) if source != "ADMIN_WEB" else None
    status_token_hash = hashlib.sha256(status_token.encode()).hexdigest() if status_token else None
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction):
        idem_snapshot = idem_ref.get(transaction=tx)
        if idem_snapshot.exists:
            existing = idem_snapshot.to_dict() or {}
            if existing.get("requestHash") != digest:
                raise IdempotencyConflict("Idempotency-Key was already used with different data")
            replay = {
                "bookingId": existing["publicBookingId"],
                "status": existing["status"],
                "subtotalAmountSatang": existing.get(
                    "subtotalAmountSatang", existing["estimatedAmountSatang"]
                ),
                "discountAmountSatang": existing.get("discountAmountSatang", 0),
                "estimatedAmountSatang": existing["estimatedAmountSatang"],
                "tipAmountSatang": existing.get("tipAmountSatang", 0),
                "grossAmountSatang": existing.get(
                    "grossAmountSatang",
                    int(existing["estimatedAmountSatang"])
                    + int(existing.get("tipAmountSatang", 0)),
                ),
                "idempotentReplay": True,
            }
            if existing.get("statusToken"):
                replay["statusToken"] = existing["statusToken"]
            return replay

        branch_snapshot = branch_ref.get(transaction=tx)
        if not branch_snapshot.exists:
            raise ValidationDomainError("Branch is not configured")
        branch = branch_snapshot.to_dict() or {}
        if historical_record:
            _validate_historical_record_window(
                start_at,
                now=now,
                bucket_minutes=settings.capacity_bucket_minutes,
            )
        elif source == "ADMIN_WEB" and admin_booking_mode == "WALK_IN":
            _validate_walk_in_window(
                start_at,
                now=now,
                bucket_minutes=settings.capacity_bucket_minutes,
            )
        elif source == "ADMIN_WEB":
            _validate_staff_assisted_window(
                start_at,
                now=now,
                bucket_minutes=settings.capacity_bucket_minutes,
            )
        else:
            _validate_advance_window(start_at, branch)
        capacity = 0
        if not historical_record:
            _validate_operating_hours(start_at, max_duration, branch)
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

        if e164 and source == "ADMIN_WEB":
            same_slot = list(
                client.collection("bookings")
                .where("branchId", "==", branch_id)
                .where("startAt", "==", start_at)
                .limit(20)
                .stream(transaction=tx)
            )
            if any(
                (item.to_dict() or {}).get("status") in {"PENDING", "CONFIRMED", "IN_SERVICE"}
                and ((item.to_dict() or {}).get("contact") or {}).get("phoneE164") == e164
                for item in same_slot
            ):
                raise DuplicateBooking("An active booking already exists for this phone and time")
        elif e164:
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
            "status": initial_status,
            "subtotalAmountSatang": subtotal,
            "discountAmountSatang": discount_amount_satang,
            "estimatedAmountSatang": total,
            "tipAmountSatang": tip_amount_satang,
            "grossAmountSatang": gross_total,
            "version": 1,
            "idempotentReplay": False,
        }
        if status_token:
            result["statusToken"] = status_token
        contact = (
            {"mode": "PHONE", "phoneMasked": mask_phone(e164), "phoneE164": e164}
            if e164
            else {"mode": "NONE"}
        )
        booking_data = {
            "publicBookingId": public_id,
            "branchId": branch_id,
            "source": source,
            "status": initial_status,
            "customerListBucket": customer_list_bucket(initial_status),
            "contact": contact,
            "adminEntryMode": admin_booking_mode,
            "customerName": str(selections[0][0].get("nickname", "Guest")),
            "serviceName": selections[0][1].name_en,
            "serviceId": selections[0][1].id,
            "serviceNameTh": selections[0][1].name_th,
            "serviceNameEn": selections[0][1].name_en,
            "serviceNamesTh": [service.name_th for _, service, _ in selections],
            "serviceNamesEn": [service.name_en for _, service, _ in selections],
            "startAt": start_at,
            "endAt": start_at + timedelta(minutes=max_duration),
            "localDate": date,
            "localStartTime": time,
            "timezone": "Asia/Bangkok",
            "pax": len(selections),
            "subtotalAmountSatang": subtotal,
            "discountAmountSatang": discount_amount_satang,
            "estimatedAmountSatang": total,
            "tipAmountSatang": tip_amount_satang,
            "grossAmountSatang": gross_total,
            "priceIncludesVat": True,
            "paymentStatus": "UNAVAILABLE",
            "financiallyExcluded": False,
            "historicalFinancialRecord": historical_record,
            "healthAlert": any(bool(p.get("hasHealthInformation")) for p, _, _ in selections),
            "assignmentState": "NOT_REQUIRED" if historical_record else "UNASSIGNED",
            "capacityReleased": historical_record,
            "version": 1,
            "createdAt": now,
            "updatedAt": now,
        }
        if status_token_hash:
            booking_data["statusTokenHash"] = status_token_hash
        if source == "ADMIN_WEB" and not historical_record:
            booking_data["confirmedAt"] = now
            booking_data["confirmedBy"] = actor_id
        if discount_amount_satang:
            booking_data["discountType"] = "ADMIN_FIXED"
            booking_data["discountReason"] = normalized_discount_reason
            booking_data["discountAppliedBy"] = actor_id
            booking_data["discountAppliedAt"] = now
        if historical_record:
            booking_data["recordedAt"] = now
            booking_data["recordedBy"] = actor_id
        else:
            booking_data["capacityReservation"] = {
                "bucketIds": [ref.id for ref in bucket_refs],
                "units": units,
            }
        if line_identity:
            booking_data["lineIdentityHash"] = line_identity_hash(
                str(line_identity["sub"]), str(line_identity.get("aud", ""))
            )
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
                    "lineTotalSatang": (
                        variant.price_satang
                        if variant.pricing_mode == "PER_PARTICIPANT" or index == 1
                        else 0
                    ),
                    "financiallyExcluded": False,
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
                    "captureMethod": consent_capture_method,
                    "capturedByActorId": actor_id,
                    "acceptedAt": now,
                },
            )

        if booking_privacy_acknowledged:
            privacy_consent_ref = client.collection("consent_evidence").document()
            tx.set(
                privacy_consent_ref,
                {
                    "bookingDocId": booking_ref.id,
                    "purpose": "BOOKING_PRIVACY_ACK",
                    "accepted": True,
                    "version": settings.privacy_notice_version,
                    "termsVersion": settings.booking_terms_version,
                    "captureMethod": consent_capture_method,
                    "capturedByActorId": actor_id,
                    "acceptedAt": now,
                },
            )

        audit_ref = client.collection("audit_events").document()
        audit_data: dict[str, object] = {
            "eventType": (
                "BOOKING_HISTORY_RECORDED" if historical_record else "BOOKING_CREATED"
            ),
            "bookingDocId": booking_ref.id,
            "publicBookingId": public_id,
            "actorType": "ADMIN_USER" if source == "ADMIN_WEB" else (
                "LINE_CUSTOMER" if line_identity else "GUEST"
            ),
            "source": source,
            "toStatus": initial_status,
            "financiallyExcluded": False,
            "historicalFinancialRecord": historical_record,
            "subtotalAmountSatang": subtotal,
            "discountAmountSatang": discount_amount_satang,
            "estimatedAmountSatang": total,
            "tipAmountSatang": tip_amount_satang,
            "grossAmountSatang": gross_total,
            "createdAt": now,
        }
        if actor_id:
            audit_data["actorId"] = actor_id
        tx.set(audit_ref, audit_data)

        if discount_amount_satang:
            discount_audit_ref = client.collection("audit_events").document()
            tx.set(
                discount_audit_ref,
                {
                    "eventType": "BOOKING_DISCOUNT_APPLIED",
                    "bookingDocId": booking_ref.id,
                    "publicBookingId": public_id,
                    "actorType": "ADMIN_USER",
                    "actorId": actor_id,
                    "actorRole": actor_role,
                    "discountType": "ADMIN_FIXED",
                    "subtotalAmountSatang": subtotal,
                    "discountAmountSatang": discount_amount_satang,
                    "finalAmountSatang": total,
                    "reason": normalized_discount_reason,
                    "createdAt": now,
                },
            )

        if not historical_record:
            event_ref = client.collection("notification_outbox").document()
            tx.set(
                event_ref,
                {
                    "eventId": event_ref.id,
                    "eventType": "BOOKING_CREATED",
                    "aggregateId": booking_ref.id,
                    "publicBookingId": public_id,
                    "bookingStatus": initial_status,
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
        idempotency_data: dict[str, object] = {
            "requestHash": digest,
            "publicBookingId": public_id,
            "status": initial_status,
            "subtotalAmountSatang": subtotal,
            "discountAmountSatang": discount_amount_satang,
            "estimatedAmountSatang": total,
            "tipAmountSatang": tip_amount_satang,
            "grossAmountSatang": gross_total,
            "bookingDocId": booking_ref.id,
            "expiresAt": now + timedelta(hours=24),
            "createdAt": now,
        }
        if status_token:
            idempotency_data["statusToken"] = status_token
        tx.set(idem_ref, idempotency_data)
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
    data["contactMode"] = contact.get("mode", "PHONE" if contact.get("phoneE164") else "NONE")
    data["startLocal"] = data.get("startAt")
    data["durationMinutes"] = (
        int((end_at - start_at).total_seconds() // 60)
        if isinstance(end_at, datetime) and isinstance(start_at, datetime)
        else 0
    )
    data.setdefault("therapistName", None)
    data.setdefault("healthAlert", False)
    return data
