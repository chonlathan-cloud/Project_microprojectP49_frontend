#!/usr/bin/env python3
"""Create the versioned welcome-50 campaign config. Dry-run is the default."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from google.cloud import firestore

DEFAULT_PROJECT = "the49-487609"
DEFAULT_DATABASE = "spa-test-db"
CAMPAIGN_CODE = "welcome-50"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    parser.add_argument("--allow-update", action="store_true")
    args = parser.parse_args()
    if args.apply and args.confirm_database != args.database:
        parser.error("--apply requires --confirm-database matching --database exactly")
    if not args.apply and args.confirm_database:
        parser.error("--confirm-database is only valid with --apply")
    if args.database == "(default)":
        parser.error("the Receipt (default) database is outside the SPA boundary")
    return args


def campaign_document() -> dict[str, object]:
    return {
        "code": CAMPAIGN_CODE,
        "status": "ACTIVE",
        "branchId": "branch_001",
        "nameTh": "รับส่วนลด 50 บาท",
        "nameEn": "Get THB 50 off",
        "descriptionTh": "ลงทะเบียนครั้งเดียวเพื่อรับคูปองส่วนลดสำหรับใช้ที่ SPA 49",
        "descriptionEn": "Register once to receive a SPA 49 discount coupon.",
        "benefit": {
            "type": "FIXED_DISCOUNT",
            "amountSatang": 5000,
            "currency": "THB",
        },
        "eligibility": {
            "maxClaimsPerCustomer": 1,
            "requiresFollowing": True,
            "allowLiffFriendshipEvidence": True,
        },
        "form": {
            "requiredFields": ["fullName", "phone", "birthDay", "birthMonth"],
            "optionalFields": ["gender"],
        },
        "privacyNoticeVersion": "privacy-draft-v2",
        "requiredPurposeIds": ["COUPON_FULFILLMENT"],
        "optionalPurposeIds": ["BIRTHDAY_MARKETING"],
        "schemaVersion": 1,
        "version": 1,
    }


def main() -> int:
    args = parse_args()
    client = firestore.Client(project=args.project, database=args.database)
    ref = client.collection("campaigns").document(CAMPAIGN_CODE)
    existing = ref.get()
    action = "update" if existing.exists else "create"
    print(f"Project: {args.project}")
    print(f"Database: {args.database}")
    print(f"Document: campaigns/{CAMPAIGN_CODE}")
    print(f"Action: {action}")
    print("Coupon expiry: not configured (the API will not invent one)")
    if existing.exists and not args.allow_update:
        print("No write: document exists; use --allow-update after reviewing the diff.")
        return 0
    if not args.apply:
        print("Dry-run only. Add --apply and matching --confirm-database to write.")
        return 0
    payload = campaign_document()
    payload["updatedAt"] = datetime.now(UTC)
    if not existing.exists:
        payload["createdAt"] = payload["updatedAt"]
    ref.set(payload, merge=args.allow_update)
    print("Campaign config written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
