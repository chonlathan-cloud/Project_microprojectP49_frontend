from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from google.cloud import firestore

from app.core.errors import (
    ConflictDomainError,
    InvalidStateTransition,
    NotFoundDomainError,
    ValidationDomainError,
)
from app.core.settings import get_settings

ADMIN_PERMISSIONS = {
    "manageCampaigns": True,
    "viewPii": True,
    "exportCrm": True,
    "searchCoupons": True,
    "redeemCoupons": True,
    "voidCoupons": True,
}
STAFF_PERMISSIONS = {
    "manageCampaigns": False,
    "viewPii": False,
    "exportCrm": False,
    "searchCoupons": True,
    "redeemCoupons": True,
    "voidCoupons": False,
}


def permissions_for(actor: dict[str, object]) -> dict[str, bool]:
    return dict(ADMIN_PERMISSIONS if actor.get("role") == "ADMIN" else STAFF_PERMISSIONS)


def actor_branch_ids(actor: dict[str, object]) -> list[str]:
    configured = actor.get("branchIds")
    if isinstance(configured, list):
        branches = [str(value) for value in configured if str(value).strip()]
        if branches:
            return branches
    return [get_settings().default_branch_id]


def require_permission(actor: dict[str, object], permission: str) -> None:
    if not permissions_for(actor).get(permission, False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")


def require_branch(actor: dict[str, object], branch_id: str) -> None:
    if branch_id not in actor_branch_ids(actor):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Branch access denied")


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _campaign_item(code: str, data: dict[str, object]) -> dict[str, object]:
    benefit = data.get("benefit") if isinstance(data.get("benefit"), dict) else {}
    return {
        "code": code,
        "branchId": data.get("branchId"),
        "nameTh": data.get("nameTh", ""),
        "nameEn": data.get("nameEn", ""),
        "descriptionTh": data.get("descriptionTh"),
        "descriptionEn": data.get("descriptionEn"),
        "status": data.get("status", "DRAFT"),
        "amountSatang": int(benefit.get("amountSatang", 0)),
        "currency": benefit.get("currency", "THB"),
        "startsAt": data.get("startsAt"),
        "endsAt": data.get("endsAt"),
        "couponExpiresAt": data.get("couponExpiresAt"),
        "version": int(data.get("version", 1)),
        "updatedAt": data.get("updatedAt"),
    }


def _mask_name(value: object) -> str:
    parts = str(value or "").split()
    return " ".join(f"{part[0]}***" if part else "" for part in parts)


def list_campaigns(
    client: firestore.Client, actor: dict[str, object], branch_id: str
) -> list[dict[str, object]]:
    require_branch(actor, branch_id)
    snapshots = client.collection("campaigns").where("branchId", "==", branch_id).stream()
    items = [_campaign_item(snapshot.id, snapshot.to_dict() or {}) for snapshot in snapshots]
    return sorted(items, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)


def update_campaign(
    client: firestore.Client,
    actor: dict[str, object],
    campaign_code: str,
    changes: dict[str, object],
    expected_version: int,
    now: datetime | None = None,
) -> dict[str, object]:
    require_permission(actor, "manageCampaigns")
    ref = client.collection("campaigns").document(campaign_code)
    audit_ref = client.collection("audit_events").document()
    transaction = client.transaction()
    current_time = now or datetime.now(UTC)

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        snapshot = ref.get(transaction=tx)
        if not snapshot.exists:
            raise NotFoundDomainError("Campaign not found")
        campaign = snapshot.to_dict() or {}
        require_branch(actor, str(campaign.get("branchId", "")))
        version = int(campaign.get("version", 1))
        if version != expected_version:
            raise ConflictDomainError("Campaign was changed by another user")
        if "amountSatang" in changes and campaign.get("status", "DRAFT") != "DRAFT":
            raise InvalidStateTransition("Discount amount can only be changed while DRAFT")

        update: dict[str, object] = {}
        for field in (
            "nameTh",
            "nameEn",
            "descriptionTh",
            "descriptionEn",
            "startsAt",
            "endsAt",
            "couponExpiresAt",
        ):
            if field in changes:
                update[field] = changes[field]
        if "amountSatang" in changes:
            amount = int(changes["amountSatang"])
            if amount <= 0:
                raise ValidationDomainError("Discount amount must be greater than zero")
            benefit = dict(campaign.get("benefit") or {})
            benefit["amountSatang"] = amount
            benefit.setdefault("type", "FIXED_DISCOUNT")
            benefit.setdefault("currency", "THB")
            update["benefit"] = benefit
        update.update(
            {"version": version + 1, "updatedAt": current_time, "updatedBy": actor.get("uid")}
        )
        merged = {**campaign, **update}
        _validate_dates(merged, activating=str(merged.get("status")) in {"ACTIVE", "PAUSED"})
        tx.update(ref, update)
        tx.set(
            audit_ref,
            {
                "eventType": "CAMPAIGN_UPDATED",
                "actorUid": actor.get("uid"),
                "campaignCode": campaign_code,
                "changedFields": sorted(changes),
                "recordedAt": current_time,
            },
        )
        return _campaign_item(campaign_code, merged)

    return write(transaction)


def _validate_dates(campaign: dict[str, object], *, activating: bool) -> None:
    starts_at, ends_at, expires_at = (
        _utc(campaign.get(field)) for field in ("startsAt", "endsAt", "couponExpiresAt")
    )
    if activating and (not starts_at or not ends_at or not expires_at):
        raise ValidationDomainError("Start, end, and coupon expiry are required before activation")
    if starts_at and ends_at and starts_at >= ends_at:
        raise ValidationDomainError("Campaign end must be after start")
    if ends_at and expires_at and expires_at < ends_at:
        raise ValidationDomainError("Coupon expiry must be on or after campaign end")


def transition_campaign(
    client: firestore.Client,
    actor: dict[str, object],
    campaign_code: str,
    target_status: str,
    expected_version: int,
    command_id: str,
    now: datetime | None = None,
) -> dict[str, object]:
    require_permission(actor, "manageCampaigns")
    ref = client.collection("campaigns").document(campaign_code)
    command_ref = client.collection("admin_commands").document(
        hashlib.sha256(f"{actor.get('uid')}:{command_id}".encode()).hexdigest()
    )
    audit_ref = client.collection("audit_events").document()
    transaction = client.transaction()
    current_time = now or datetime.now(UTC)
    allowed = {
        "DRAFT": {"ACTIVE"},
        "ACTIVE": {"PAUSED", "ENDED"},
        "PAUSED": {"ACTIVE", "ENDED"},
        "ENDED": set(),
    }

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        command = command_ref.get(transaction=tx)
        if command.exists:
            return dict((command.to_dict() or {}).get("response") or {})
        snapshot = ref.get(transaction=tx)
        if not snapshot.exists:
            raise NotFoundDomainError("Campaign not found")
        campaign = snapshot.to_dict() or {}
        require_branch(actor, str(campaign.get("branchId", "")))
        current_status = str(campaign.get("status", "DRAFT"))
        version = int(campaign.get("version", 1))
        if version != expected_version:
            raise ConflictDomainError("Campaign was changed by another user")
        if target_status not in allowed.get(current_status, set()):
            raise InvalidStateTransition(
                f"Campaign cannot transition from {current_status} to {target_status}"
            )
        if target_status == "ACTIVE":
            _validate_dates(campaign, activating=True)
        update = {
            "status": target_status,
            "version": version + 1,
            "updatedAt": current_time,
            "updatedBy": actor.get("uid"),
        }
        response = _campaign_item(campaign_code, {**campaign, **update})
        tx.update(ref, update)
        tx.set(
            audit_ref,
            {
                "eventType": "CAMPAIGN_STATUS_CHANGED",
                "actorUid": actor.get("uid"),
                "campaignCode": campaign_code,
                "previousStatus": current_status,
                "status": target_status,
                "recordedAt": current_time,
            },
        )
        tx.set(
            command_ref,
            {
                "actorUid": actor.get("uid"),
                "commandId": command_id,
                "response": response,
                "createdAt": current_time,
            },
        )
        return response

    return write(transaction)


def _masked_customer(
    client: firestore.Client, participation: dict[str, object]
) -> dict[str, object] | None:
    customer_id = str(participation.get("customerId", ""))
    customer_snapshot = client.collection("customers").document(customer_id).get()
    if not customer_snapshot.exists:
        return None
    customer = customer_snapshot.to_dict() or {}
    marketing_snapshot = client.collection("marketing_profiles").document(customer_id).get()
    marketing = marketing_snapshot.to_dict() or {} if marketing_snapshot.exists else {}
    marketing_status = str(marketing.get("birthdayMarketingStatus", "UNKNOWN"))
    return {
        "customerId": customer_id,
        "displayName": _mask_name(customer.get("displayName")),
        "phoneMasked": customer.get("phoneMasked"),
        "friendStatus": customer.get("friendStatus", "UNKNOWN"),
        "campaignCode": participation.get("campaignCode"),
        "claimedAt": participation.get("claimedAt"),
        "couponId": participation.get("couponId"),
        "birthdayMarketingStatus": marketing_status,
        "birthYear": marketing.get("birthYear") if marketing_status == "GRANTED" else None,
    }


def list_campaign_customers(
    client: firestore.Client,
    actor: dict[str, object],
    branch_id: str,
    campaign_code: str | None,
    marketing_status: str | None,
    query: str | None,
    limit: int,
) -> list[dict[str, object]]:
    require_branch(actor, branch_id)
    campaign_codes = {item["code"] for item in list_campaigns(client, actor, branch_id)}
    if campaign_code and campaign_code not in campaign_codes:
        raise HTTPException(status_code=403, detail="Branch access denied")
    source = client.collection("campaign_participations")
    if campaign_code:
        source = source.where("campaignCode", "==", campaign_code)
    items: list[dict[str, object]] = []
    needle = (query or "").strip().lower()
    # Consent/query filters are applied after joining customer documents, so fetch
    # enough candidates to fill the requested result without silently truncating CSV.
    for snapshot in source.limit(min(max(limit * 3, limit), 15_000)).stream():
        participation = snapshot.to_dict() or {}
        if participation.get("campaignCode") not in campaign_codes:
            continue
        item = _masked_customer(client, participation)
        if not item or (marketing_status and item["birthdayMarketingStatus"] != marketing_status):
            continue
        haystack = " ".join(
            [
                str(item["customerId"]),
                str(item.get("displayName", "")),
                str(item.get("phoneMasked", "")),
            ]
        ).lower()
        if needle and needle not in haystack:
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


def reveal_customer_pii(
    client: firestore.Client,
    actor: dict[str, object],
    customer_id: str,
    branch_id: str,
    reason: str,
    now: datetime | None = None,
) -> dict[str, object]:
    require_permission(actor, "viewPii")
    require_branch(actor, branch_id)
    participations = (
        client.collection("campaign_participations")
        .where("customerId", "==", customer_id)
        .limit(200)
        .stream()
    )
    campaign_codes = {item["code"] for item in list_campaigns(client, actor, branch_id)}
    if not any(
        (snapshot.to_dict() or {}).get("campaignCode") in campaign_codes
        for snapshot in participations
    ):
        raise NotFoundDomainError("Customer not found")
    normalized_reason = " ".join(reason.split())
    if len(normalized_reason) < 5:
        raise ValidationDomainError("PII access reason is required")
    private_ref = client.collection("customer_private").document(customer_id)
    audit_ref = client.collection("audit_events").document()
    transaction = client.transaction()
    current_time = now or datetime.now(UTC)

    @firestore.transactional
    def read_and_audit(tx: firestore.Transaction) -> dict[str, object]:
        snapshot = private_ref.get(transaction=tx)
        if not snapshot.exists:
            raise NotFoundDomainError("Customer private profile not found")
        private = snapshot.to_dict() or {}
        tx.set(
            audit_ref,
            {
                "eventType": "CUSTOMER_PII_ACCESSED",
                "actorUid": actor.get("uid"),
                "customerId": customer_id,
                "reason": normalized_reason,
                "recordedAt": current_time,
            },
        )
        return {
            key: private.get(key)
            for key in ("fullName", "phoneE164", "birthDay", "birthMonth", "birthYear", "gender")
        }

    return read_and_audit(transaction)


def export_campaign_customers_csv(
    client: firestore.Client,
    actor: dict[str, object],
    branch_id: str,
    campaign_code: str | None,
    now: datetime | None = None,
) -> str:
    require_permission(actor, "exportCrm")
    rows = list_campaign_customers(client, actor, branch_id, campaign_code, "GRANTED", None, 5000)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "customerId",
            "fullName",
            "phoneE164",
            "birthMonth",
            "birthDay",
            "birthYear",
            "birthYearBuddhist",
            "gender",
            "friendStatus",
            "campaignCode",
            "claimedAt",
            "birthdayMarketingStatus",
        ],
    )
    writer.writeheader()
    for row in rows:
        private_snapshot = (
            client.collection("customer_private").document(str(row["customerId"])).get()
        )
        private = private_snapshot.to_dict() or {} if private_snapshot.exists else {}
        writer.writerow(
            {
                "customerId": row["customerId"],
                "fullName": private.get("fullName"),
                "phoneE164": private.get("phoneE164"),
                "birthMonth": private.get("birthMonth"),
                "birthDay": private.get("birthDay"),
                "birthYear": private.get("birthYear"),
                "birthYearBuddhist": (
                    int(private["birthYear"]) + 543 if private.get("birthYear") else None
                ),
                "gender": private.get("gender"),
                "friendStatus": row.get("friendStatus"),
                "campaignCode": row.get("campaignCode"),
                "claimedAt": row.get("claimedAt"),
                "birthdayMarketingStatus": row.get("birthdayMarketingStatus"),
            }
        )
    client.collection("audit_events").document().set(
        {
            "eventType": "CRM_CUSTOMERS_EXPORTED",
            "actorUid": actor.get("uid"),
            "branchId": branch_id,
            "campaignCode": campaign_code,
            "recordCount": len(rows),
            "consentFilter": "BIRTHDAY_MARKETING=GRANTED",
            "recordedAt": now or datetime.now(UTC),
        }
    )
    return "\ufeff" + output.getvalue()


def search_coupon(
    client: firestore.Client,
    actor: dict[str, object],
    branch_id: str,
    code: str,
    now: datetime | None = None,
) -> dict[str, object]:
    require_permission(actor, "searchCoupons")
    require_branch(actor, branch_id)
    snapshots = list(
        client.collection("coupons").where("code", "==", code.strip().upper()).limit(1).stream()
    )
    if not snapshots:
        raise NotFoundDomainError("Coupon not found")
    snapshot = snapshots[0]
    coupon = snapshot.to_dict() or {}
    campaign_snapshot = (
        client.collection("campaigns").document(str(coupon.get("campaignCode", ""))).get()
    )
    campaign = campaign_snapshot.to_dict() or {} if campaign_snapshot.exists else {}
    if campaign.get("branchId") != branch_id:
        raise NotFoundDomainError("Coupon not found")
    customer_snapshot = (
        client.collection("customers").document(str(coupon.get("customerId", ""))).get()
    )
    customer = customer_snapshot.to_dict() or {} if customer_snapshot.exists else {}
    effective_status = coupon.get("status")
    expires_at = _utc(coupon.get("expiresAt"))
    if effective_status == "ISSUED" and expires_at and (now or datetime.now(UTC)) > expires_at:
        effective_status = "EXPIRED"
    return {
        "couponId": snapshot.id,
        "code": coupon.get("code"),
        "campaignCode": coupon.get("campaignCode"),
        "campaignName": campaign.get("nameTh") or campaign.get("nameEn"),
        "customerId": coupon.get("customerId"),
        "customerDisplayName": _mask_name(customer.get("displayName")),
        "customerPhoneMasked": customer.get("phoneMasked"),
        "status": coupon.get("status"),
        "effectiveStatus": effective_status,
        "amountSatang": coupon.get("amountSatang"),
        "currency": coupon.get("currency", "THB"),
        "issuedAt": coupon.get("issuedAt"),
        "expiresAt": coupon.get("expiresAt"),
        "redeemedAt": coupon.get("redeemedAt"),
        "voidedAt": coupon.get("voidedAt"),
        "version": int(coupon.get("version", 1)),
    }


def transition_coupon(
    client: firestore.Client,
    actor: dict[str, object],
    coupon_id: str,
    action: str,
    branch_id: str,
    expected_version: int,
    command_id: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    require_permission(actor, "redeemCoupons" if action == "REDEEMED" else "voidCoupons")
    require_branch(actor, branch_id)
    current_time = now or datetime.now(UTC)
    coupon_ref = client.collection("coupons").document(coupon_id)
    command_ref = client.collection("admin_commands").document(
        hashlib.sha256(f"{actor.get('uid')}:{command_id}".encode()).hexdigest()
    )
    audit_ref = client.collection("audit_events").document()
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        command = command_ref.get(transaction=tx)
        if command.exists:
            return dict((command.to_dict() or {}).get("response") or {})
        snapshot = coupon_ref.get(transaction=tx)
        if not snapshot.exists:
            raise NotFoundDomainError("Coupon not found")
        coupon = snapshot.to_dict() or {}
        campaign_ref = client.collection("campaigns").document(str(coupon.get("campaignCode", "")))
        campaign_snapshot = campaign_ref.get(transaction=tx)
        campaign = campaign_snapshot.to_dict() or {} if campaign_snapshot.exists else {}
        if campaign.get("branchId") != branch_id:
            raise NotFoundDomainError("Coupon not found")
        version = int(coupon.get("version", 1))
        if version != expected_version:
            raise ConflictDomainError("Coupon was changed by another user")
        if coupon.get("status") != "ISSUED":
            raise InvalidStateTransition("Coupon is no longer available")
        expires_at = _utc(coupon.get("expiresAt"))
        if expires_at and current_time > expires_at:
            raise InvalidStateTransition("Coupon has expired")
        normalized_reason = " ".join((reason or "").split())
        if action == "VOID" and len(normalized_reason) < 5:
            raise ValidationDomainError("Void reason is required")
        event = "COUPON_REDEEMED" if action == "REDEEMED" else "COUPON_VOIDED"
        timestamp_field = "redeemedAt" if action == "REDEEMED" else "voidedAt"
        update: dict[str, Any] = {
            "status": action,
            timestamp_field: current_time,
            "version": version + 1,
            "updatedAt": current_time,
        }
        update["redeemedBy" if action == "REDEEMED" else "voidedBy"] = actor.get("uid")
        if action == "VOID":
            update["voidReason"] = normalized_reason
        response = {
            "couponId": coupon_id,
            "code": coupon.get("code"),
            "status": action,
            "version": version + 1,
            timestamp_field: current_time,
        }
        tx.update(coupon_ref, update)
        tx.set(
            audit_ref,
            {
                "eventType": event,
                "actorUid": actor.get("uid"),
                "couponId": coupon_id,
                "campaignCode": coupon.get("campaignCode"),
                "branchId": branch_id,
                "reason": normalized_reason or None,
                "recordedAt": current_time,
            },
        )
        tx.set(
            command_ref,
            {
                "actorUid": actor.get("uid"),
                "commandId": command_id,
                "response": response,
                "createdAt": current_time,
            },
        )
        return response

    return write(transaction)
