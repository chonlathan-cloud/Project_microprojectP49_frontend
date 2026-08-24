from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from google.cloud import firestore

from app.core.errors import (
    IdempotencyConflict,
    LineFriendshipRequired,
    NotFoundDomainError,
    ValidationDomainError,
)
from app.core.settings import get_settings
from app.domains.customers.line_friendship import (
    client_attested_friendship_record,
    friendship_ref,
)
from app.domains.customers.phone import mask_phone, normalize_thai_phone
from app.integrations.line_identity import line_identity_hash


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(canonical)


def _as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _assert_campaign_available(campaign: dict[str, object], now: datetime) -> None:
    if campaign.get("status") != "ACTIVE":
        raise NotFoundDomainError("Campaign is not available")
    starts_at = _as_utc(campaign.get("startsAt"))
    ends_at = _as_utc(campaign.get("endsAt"))
    if starts_at and now < starts_at:
        raise NotFoundDomainError("Campaign is not available")
    if ends_at and now >= ends_at:
        raise NotFoundDomainError("Campaign is not available")


def _safe_campaign(campaign_code: str, campaign: dict[str, object]) -> dict[str, object]:
    benefit = campaign.get("benefit") if isinstance(campaign.get("benefit"), dict) else {}
    eligibility = (
        campaign.get("eligibility")
        if isinstance(campaign.get("eligibility"), dict)
        else {}
    )
    return {
        "code": campaign_code,
        "nameTh": campaign.get("nameTh", "รับส่วนลด 50 บาท"),
        "nameEn": campaign.get("nameEn", "Get THB 50 off"),
        "descriptionTh": campaign.get("descriptionTh"),
        "descriptionEn": campaign.get("descriptionEn"),
        "benefit": {
            "type": benefit.get("type", "FIXED_DISCOUNT"),
            "amountSatang": int(benefit.get("amountSatang", 0)),
            "currency": benefit.get("currency", "THB"),
        },
        "privacyNoticeVersion": campaign.get(
            "privacyNoticeVersion", get_settings().privacy_notice_version
        ),
        "endsAt": campaign.get("endsAt"),
        "couponExpiresAt": campaign.get("couponExpiresAt"),
        "eligibility": {
            "requiresFollowing": bool(eligibility.get("requiresFollowing", False))
        },
    }


def get_public_campaign(
    client: firestore.Client, campaign_code: str, *, now: datetime | None = None
) -> dict[str, object]:
    snapshot = client.collection("campaigns").document(campaign_code).get()
    if not snapshot.exists:
        raise NotFoundDomainError("Campaign is not available")
    campaign = snapshot.to_dict() or {}
    _assert_campaign_available(campaign, now or datetime.now(UTC))
    return _safe_campaign(campaign_code, campaign)


def claim_campaign(
    client: firestore.Client,
    *,
    campaign_code: str,
    full_name: str,
    phone: str,
    birth_day: int,
    birth_month: int,
    gender: str | None,
    privacy_acknowledged: bool,
    birthday_marketing_consent: bool,
    idempotency_key: str | None,
    line_identity: dict[str, object],
    line_friendship_confirmed: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
        raise ValidationDomainError("Idempotency-Key is required")
    if not privacy_acknowledged:
        raise ValidationDomainError("Privacy acknowledgement is required")
    if birth_day > monthrange(2000, birth_month)[1]:
        raise ValidationDomainError("Birth day is invalid for the selected month")

    normalized_name = " ".join(full_name.split())
    if len(normalized_name) < 2:
        raise ValidationDomainError("Full name is required")
    phone_e164 = normalize_thai_phone(phone)
    line_user_id = str(line_identity.get("sub", ""))
    if not line_user_id:
        raise ValidationDomainError("Verified LINE identity is required")

    settings = get_settings()
    current_time = now or datetime.now(UTC)
    identity_hash = line_identity_hash(
        line_user_id, settings.line_customer_login_channel_id
    )
    request_payload: dict[str, object] = {
        "campaignCode": campaign_code,
        "fullName": normalized_name,
        "phoneE164": phone_e164,
        "birthDay": birth_day,
        "birthMonth": birth_month,
        "gender": gender,
        "privacyAcknowledged": privacy_acknowledged,
        "birthdayMarketingConsent": birthday_marketing_consent,
        "lineFriendshipConfirmed": line_friendship_confirmed,
        "lineIdentityHash": identity_hash,
    }
    request_hash = _request_hash(request_payload)

    campaign_ref = client.collection("campaigns").document(campaign_code)
    identity_ref = client.collection("customer_identity_links").document(identity_hash)
    line_friendship_ref = friendship_ref(
        client,
        line_user_id=line_user_id,
        channel_id=settings.line_customer_login_channel_id,
    )
    idempotency_ref = client.collection("campaign_claim_idempotency").document(
        _digest(idempotency_key)
    )
    new_customer_ref = client.collection("customers").document()
    participation_id = _digest(f"{campaign_code}:{identity_hash}")
    participation_ref = client.collection("campaign_participations").document(participation_id)
    new_coupon_ref = client.collection("coupons").document()
    privacy_receipt_ref = client.collection("consent_receipts").document()
    marketing_receipt_ref = client.collection("consent_receipts").document()
    audit_ref = client.collection("audit_events").document()
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        idempotency_snapshot = idempotency_ref.get(transaction=tx)
        if idempotency_snapshot.exists:
            existing_idempotency = idempotency_snapshot.to_dict() or {}
            if existing_idempotency.get("requestHash") != request_hash:
                raise IdempotencyConflict(
                    "Idempotency-Key was already used with different data"
                )
            return dict(existing_idempotency.get("response") or {})

        campaign_snapshot = campaign_ref.get(transaction=tx)
        if not campaign_snapshot.exists:
            raise NotFoundDomainError("Campaign is not available")
        campaign = campaign_snapshot.to_dict() or {}
        _assert_campaign_available(campaign, current_time)

        identity_snapshot = identity_ref.get(transaction=tx)
        identity = identity_snapshot.to_dict() or {} if identity_snapshot.exists else {}
        friendship_snapshot = line_friendship_ref.get(transaction=tx)
        friendship = (
            friendship_snapshot.to_dict() or {} if friendship_snapshot.exists else {}
        )
        eligibility = (
            campaign.get("eligibility")
            if isinstance(campaign.get("eligibility"), dict)
            else {}
        )
        server_following = (
            friendship.get("status") == "FOLLOWING"
            or identity.get("friendStatus") == "FOLLOWING"
        )
        requires_following = bool(eligibility.get("requiresFollowing"))
        allow_liff_evidence = bool(eligibility.get("allowLiffFriendshipEvidence"))
        client_following = bool(
            requires_following and allow_liff_evidence and line_friendship_confirmed
        )
        if requires_following and not (server_following or client_following):
            raise LineFriendshipRequired("Active LINE OA friendship is required")
        friendship_evidence = "NOT_REQUIRED"
        if server_following:
            friendship_evidence = str(
                friendship.get("evidenceSource") or "LEGACY_WEBHOOK"
            )
        elif client_following:
            friendship_evidence = "LIFF_CLIENT"
        customer_id = str(identity.get("customerId") or new_customer_ref.id)
        customer_ref = client.collection("customers").document(customer_id)
        private_ref = client.collection("customer_private").document(customer_id)
        marketing_profile_ref = client.collection("marketing_profiles").document(customer_id)
        privacy_state_ref = client.collection("customer_consent_state").document(
            _digest(f"{customer_id}:COUPON_FULFILLMENT")
        )
        marketing_state_ref = client.collection("customer_consent_state").document(
            _digest(f"{customer_id}:BIRTHDAY_MARKETING")
        )

        participation_snapshot = participation_ref.get(transaction=tx)
        participation = (
            participation_snapshot.to_dict() or {} if participation_snapshot.exists else {}
        )
        existing_coupon_snapshot = None
        if participation.get("couponId"):
            existing_coupon_snapshot = (
                client.collection("coupons")
                .document(str(participation["couponId"]))
                .get(transaction=tx)
            )

        if existing_coupon_snapshot and existing_coupon_snapshot.exists:
            coupon = existing_coupon_snapshot.to_dict() or {}
            result = {
                "campaignCode": campaign_code,
                "alreadyClaimed": True,
                "coupon": {
                    "code": coupon.get("code"),
                    "status": coupon.get("status"),
                    "amountSatang": coupon.get("amountSatang"),
                    "currency": coupon.get("currency", "THB"),
                    "issuedAt": coupon.get("issuedAt"),
                    "expiresAt": coupon.get("expiresAt"),
                },
            }
            tx.set(
                idempotency_ref,
                {
                    "requestHash": request_hash,
                    "response": result,
                    "createdAt": current_time,
                    "expiresAt": current_time + timedelta(hours=24),
                },
            )
            return result

        benefit = campaign.get("benefit") if isinstance(campaign.get("benefit"), dict) else {}
        amount_satang = int(benefit.get("amountSatang", 0))
        if amount_satang <= 0:
            raise ValidationDomainError("Campaign benefit is not configured")
        coupon_code = f"W50-{uuid4().hex[:10].upper()}"
        coupon_expires_at = campaign.get("couponExpiresAt")
        result = {
            "campaignCode": campaign_code,
            "alreadyClaimed": False,
            "coupon": {
                "code": coupon_code,
                "status": "ISSUED",
                "amountSatang": amount_satang,
                "currency": benefit.get("currency", "THB"),
                "issuedAt": current_time,
                "expiresAt": coupon_expires_at,
            },
        }
        if not identity_snapshot.exists:
            tx.set(
                identity_ref,
                {
                    "provider": "LINE",
                    "channelId": settings.line_customer_login_channel_id,
                    "lineUserId": line_user_id,
                    "customerId": customer_id,
                    "friendStatus": (
                        "FOLLOWING"
                        if server_following
                        else "REPORTED_FOLLOWING"
                        if client_following
                        else "UNKNOWN"
                    ),
                    "friendshipEvidence": friendship_evidence,
                    "verifiedAt": current_time,
                    "createdAt": current_time,
                    "active": True,
                },
            )
        if client_following and not server_following:
            tx.set(
                line_friendship_ref,
                client_attested_friendship_record(
                    channel_id=settings.line_customer_login_channel_id,
                    observed_at=current_time,
                ),
                merge=True,
            )
        customer_data = {
            "displayName": normalized_name,
            "phoneMasked": mask_phone(phone_e164),
            "friendStatus": (
                "FOLLOWING"
                if server_following
                else "REPORTED_FOLLOWING"
                if client_following
                else identity.get("friendStatus", "UNKNOWN")
            ),
            "source": "LINE_CAMPAIGN",
            "profileCompleteness": "CAMPAIGN_REQUIRED_COMPLETE",
            "updatedAt": current_time,
        }
        if not identity_snapshot.exists:
            customer_data["createdAt"] = current_time
        tx.set(customer_ref, customer_data, merge=True)
        tx.set(
            private_ref,
            {
                "fullName": normalized_name,
                "phoneE164": phone_e164,
                "birthDay": birth_day,
                "birthMonth": birth_month,
                "birthMonthDay": f"{birth_month:02d}-{birth_day:02d}",
                "gender": gender,
                "source": "LINE_CAMPAIGN",
                "updatedAt": current_time,
            },
            merge=True,
        )
        tx.set(
            marketing_profile_ref,
            {
                "customerId": customer_id,
                "birthDay": birth_day,
                "birthMonth": birth_month,
                "birthdayMarketingStatus": (
                    "GRANTED" if birthday_marketing_consent else "DENIED"
                ),
                "updatedAt": current_time,
            },
            merge=True,
        )
        tx.set(
            new_coupon_ref,
            {
                "code": coupon_code,
                "campaignCode": campaign_code,
                "customerId": customer_id,
                "status": "ISSUED",
                "amountSatang": amount_satang,
                "currency": benefit.get("currency", "THB"),
                "issuedAt": current_time,
                "expiresAt": coupon_expires_at,
                "redeemedAt": None,
                "version": 1,
            },
        )
        tx.set(
            participation_ref,
            {
                "campaignCode": campaign_code,
                "customerId": customer_id,
                "identityHash": identity_hash,
                "couponId": new_coupon_ref.id,
                "status": "CLAIMED",
                "claimedAt": current_time,
                "friendshipEvidence": friendship_evidence,
            },
        )
        notice_version = campaign.get(
            "privacyNoticeVersion", settings.privacy_notice_version
        )
        tx.set(
            privacy_receipt_ref,
            {
                "customerId": customer_id,
                "purposeId": "COUPON_FULFILLMENT",
                "action": "ACKNOWLEDGED",
                "noticeVersion": notice_version,
                "source": "LIFF_CAMPAIGN",
                "campaignCode": campaign_code,
                "recordedAt": current_time,
            },
        )
        tx.set(
            privacy_state_ref,
            {
                "customerId": customer_id,
                "purposeId": "COUPON_FULFILLMENT",
                "status": "ACKNOWLEDGED",
                "noticeVersion": notice_version,
                "updatedAt": current_time,
            },
        )
        marketing_action = "GRANTED" if birthday_marketing_consent else "DENIED"
        tx.set(
            marketing_receipt_ref,
            {
                "customerId": customer_id,
                "purposeId": "BIRTHDAY_MARKETING",
                "action": marketing_action,
                "noticeVersion": notice_version,
                "source": "LIFF_CAMPAIGN",
                "campaignCode": campaign_code,
                "recordedAt": current_time,
            },
        )
        tx.set(
            marketing_state_ref,
            {
                "customerId": customer_id,
                "purposeId": "BIRTHDAY_MARKETING",
                "status": marketing_action,
                "noticeVersion": notice_version,
                "updatedAt": current_time,
            },
        )
        tx.set(
            audit_ref,
            {
                "eventType": "CAMPAIGN_COUPON_ISSUED",
                "campaignCode": campaign_code,
                "customerId": customer_id,
                "couponId": new_coupon_ref.id,
                "actorType": "LINE_CUSTOMER",
                "actorIdHash": identity_hash,
                "friendshipEvidence": friendship_evidence,
                "createdAt": current_time,
            },
        )
        tx.set(
            idempotency_ref,
            {
                "requestHash": request_hash,
                "response": result,
                "createdAt": current_time,
                "expiresAt": current_time + timedelta(hours=24),
            },
        )
        return result

    return write(transaction)
