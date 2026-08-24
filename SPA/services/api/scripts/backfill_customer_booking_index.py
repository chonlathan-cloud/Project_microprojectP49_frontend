#!/usr/bin/env python3
"""Backfill the privacy-safe customer booking index from verified LINE links.

Dry-run is the default. Raw LINE user IDs are read only from the existing
line_booking_links collection, are never printed, and are not copied to booking
documents. Writes require an exact database confirmation.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime

from google.cloud import firestore

from app.domains.bookings.service import customer_list_bucket
from app.integrations.line_identity import line_identity_hash

DEFAULT_PROJECT = "the49-487609"
ENVIRONMENT_DEFAULTS = {
    "test": {
        "database": "spa-test-db",
        "channel_id_secret": "spa-line-customer-login-channel-id",
    },
    "production": {
        "database": "spa-db",
        "channel_id_secret": "spa-line-prod-customer-login-channel-id-Prod",
    },
}
MAX_BATCH_WRITES = 400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=tuple(ENVIRONMENT_DEFAULTS), required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--database")
    parser.add_argument("--channel-id-secret")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    defaults = ENVIRONMENT_DEFAULTS[args.environment]
    args.database = args.database or defaults["database"]
    args.channel_id_secret = args.channel_id_secret or defaults["channel_id_secret"]
    if args.database == "(default)":
        parser.error("the Receipt (default) database is outside the SPA boundary")
    if args.apply and args.confirm_database != args.database:
        parser.error("--apply requires --confirm-database matching --database exactly")
    if not args.apply and args.confirm_database:
        parser.error("--confirm-database is only valid with --apply")
    return args


def access_secret(project: str, secret_name: str) -> str:
    completed = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--project={project}",
            f"--secret={secret_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not value:
        raise RuntimeError(f"Secret has no enabled value: {secret_name}")
    return value


def build_updates(
    client: firestore.Client, *, channel_id: str
) -> tuple[list[tuple[object, dict[str, object]]], dict[str, int]]:
    updates: list[tuple[object, dict[str, object]]] = []
    counts = {"links": 0, "eligible": 0, "missingBooking": 0, "alreadyCurrent": 0}
    for link_snapshot in client.collection("line_booking_links").stream():
        counts["links"] += 1
        link = link_snapshot.to_dict() or {}
        if not link.get("active") or link.get("channelId") != channel_id:
            continue
        line_user_id = link.get("lineUserId")
        booking_document_id = link.get("bookingDocId") or link_snapshot.id
        if not isinstance(line_user_id, str) or not line_user_id:
            continue
        booking_ref = client.collection("bookings").document(str(booking_document_id))
        booking_snapshot = booking_ref.get()
        if not booking_snapshot.exists:
            counts["missingBooking"] += 1
            continue
        booking = booking_snapshot.to_dict() or {}
        update = {
            "lineIdentityHash": line_identity_hash(line_user_id, channel_id),
            "customerListBucket": customer_list_bucket(str(booking.get("status", ""))),
        }
        if all(booking.get(key) == value for key, value in update.items()):
            counts["alreadyCurrent"] += 1
            continue
        counts["eligible"] += 1
        updates.append((booking_ref, update))
    return updates, counts


def apply_updates(
    client: firestore.Client, updates: list[tuple[object, dict[str, object]]]
) -> None:
    updated_at = datetime.now(UTC)
    for offset in range(0, len(updates), MAX_BATCH_WRITES):
        batch = client.batch()
        for reference, update in updates[offset : offset + MAX_BATCH_WRITES]:
            batch.set(reference, {**update, "updatedAt": updated_at}, merge=True)
        batch.commit()


def main() -> int:
    args = parse_args()
    channel_id = access_secret(args.project, args.channel_id_secret)
    client = firestore.Client(project=args.project, database=args.database)
    updates, counts = build_updates(client, channel_id=channel_id)
    print(f"Project: {args.project}")
    print(f"Database: {args.database}")
    print(f"LINE links scanned: {counts['links']}")
    print(f"Bookings requiring update: {counts['eligible']}")
    print(f"Missing bookings: {counts['missingBooking']}")
    print(f"Already current: {counts['alreadyCurrent']}")
    print("Raw LINE user IDs were not printed or copied.")
    if not args.apply:
        print("Dry-run only. Add --apply and matching --confirm-database to write.")
        return 0
    apply_updates(client, updates)
    client.collection("migration_runs").document().set(
        {
            "migration": "BACKFILL_CUSTOMER_BOOKING_INDEX_V1",
            "environment": args.environment,
            "database": args.database,
            "linksScanned": counts["links"],
            "bookingsUpdated": counts["eligible"],
            "missingBookings": counts["missingBooking"],
            "completedAt": datetime.now(UTC),
        }
    )
    print(f"Backfill complete: {counts['eligible']} booking documents merged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
