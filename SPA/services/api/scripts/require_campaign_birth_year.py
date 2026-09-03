#!/usr/bin/env python3
"""Safely require birth year for an existing LINE campaign. Dry-run is the default."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from google.cloud import firestore

DEFAULT_PROJECT = "the49-487609"
DEFAULT_DATABASE = "spa-test-db"
DEFAULT_CAMPAIGN = "welcome-50"
NOTICE_VERSION = "privacy-draft-v3"
SCHEMA_VERSION = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--campaign", default=DEFAULT_CAMPAIGN)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    if args.database == "(default)":
        parser.error("the Receipt (default) database is outside the SPA boundary")
    if args.apply and args.confirm_database != args.database:
        parser.error("--apply requires --confirm-database matching --database exactly")
    if not args.apply and args.confirm_database:
        parser.error("--confirm-database is only valid with --apply")
    return args


def main() -> int:
    args = parse_args()
    client = firestore.Client(project=args.project, database=args.database)
    ref = client.collection("campaigns").document(args.campaign)
    snapshot = ref.get()
    if not snapshot.exists:
        raise SystemExit(f"Campaign not found: campaigns/{args.campaign}")

    campaign = snapshot.to_dict() or {}
    form = dict(campaign.get("form") or {}) if isinstance(campaign.get("form"), dict) else {}
    original_required_fields = [str(value) for value in form.get("requiredFields", [])]
    required_fields = list(original_required_fields)
    if "birthYear" not in required_fields:
        required_fields.append("birthYear")
    form["requiredFields"] = required_fields

    current_version = int(campaign.get("version", 1))
    current_schema = int(campaign.get("schemaVersion", 1))
    already_configured = (
        "birthYear" in original_required_fields
        and campaign.get("privacyNoticeVersion") == NOTICE_VERSION
        and current_schema >= SCHEMA_VERSION
    )

    print(f"Project: {args.project}")
    print(f"Database: {args.database}")
    print(f"Campaign: {args.campaign}")
    print(f"requiredFields: {original_required_fields} -> {required_fields}")
    print(f"privacyNoticeVersion: {campaign.get('privacyNoticeVersion')} -> {NOTICE_VERSION}")
    print(f"schemaVersion: {current_schema} -> {max(current_schema, SCHEMA_VERSION)}")
    if already_configured:
        print("No write: birth-year policy already matches.")
        return 0
    if not args.apply:
        print("Dry-run only. Add --apply and matching --confirm-database to write.")
        return 0

    recorded_at = datetime.now(UTC)
    ref.update(
        {
            "form": form,
            "privacyNoticeVersion": NOTICE_VERSION,
            "schemaVersion": max(current_schema, SCHEMA_VERSION),
            "version": current_version + 1,
            "updatedAt": recorded_at,
        }
    )
    client.collection("audit_events").document().set(
        {
            "eventType": "CAMPAIGN_FORM_SCHEMA_UPDATED",
            "actorType": "MAINTENANCE_SCRIPT",
            "campaignCode": args.campaign,
            "changedFields": ["form.requiredFields", "privacyNoticeVersion", "schemaVersion"],
            "recordedAt": recorded_at,
        }
    )
    print("Campaign birth-year policy updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
