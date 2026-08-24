#!/usr/bin/env python3
"""Safely configure LINE friendship evidence for an existing campaign."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from google.cloud import firestore

DEFAULT_PROJECT = "the49-487609"
DEFAULT_DATABASE = "spa-test-db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--campaign", default="welcome-50")
    parser.add_argument(
        "--allow-liff-evidence",
        choices=("true", "false"),
        required=True,
        help="Allow the backend to accept a positive LIFF getFriendship result.",
    )
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
    eligibility = (
        dict(campaign.get("eligibility") or {})
        if isinstance(campaign.get("eligibility"), dict)
        else {}
    )
    desired = args.allow_liff_evidence == "true"
    current = bool(eligibility.get("allowLiffFriendshipEvidence"))
    print(f"Project: {args.project}")
    print(f"Database: {args.database}")
    print(f"Campaign: {args.campaign}")
    print(f"allowLiffFriendshipEvidence: {current} -> {desired}")
    if current == desired:
        print("No write: policy already matches.")
        return 0
    if not args.apply:
        print("Dry-run only. Add --apply and matching --confirm-database to write.")
        return 0
    ref.update(
        {
            "eligibility.allowLiffFriendshipEvidence": desired,
            "updatedAt": datetime.now(UTC),
        }
    )
    print("Campaign friendship policy updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
