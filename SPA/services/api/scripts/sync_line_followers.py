#!/usr/bin/env python3
"""Backfill LINE OA followers into Firestore without storing raw LINE user IDs.

The LINE followers endpoint is available only to verified or premium accounts.
Dry-run is the default. Secret values are captured from Secret Manager and are
never printed.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime

import httpx
from google.cloud import firestore

from app.domains.customers.line_friendship import (
    follower_sync_record,
    friendship_document_id,
)

DEFAULT_PROJECT = "the49-487609"
ENVIRONMENT_DEFAULTS = {
    "test": {
        "database": "spa-test-db",
        "access_token_secret": "spa-line-customer-messaging-channel-access-token",
        "channel_id_secret": "spa-line-customer-login-channel-id",
    },
    "production": {
        "database": "spa-db",
        "access_token_secret": "spa-line-prod-customer-messaging-channel-access-token-Prod",
        "channel_id_secret": "spa-line-prod-customer-login-channel-id-Prod",
    },
}
FOLLOWERS_URL = "https://api.line.me/v2/bot/followers/ids"
MAX_BATCH_WRITES = 400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=tuple(ENVIRONMENT_DEFAULTS), required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--database")
    parser.add_argument("--access-token-secret")
    parser.add_argument("--channel-id-secret")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    defaults = ENVIRONMENT_DEFAULTS[args.environment]
    args.database = args.database or defaults["database"]
    args.access_token_secret = (
        args.access_token_secret or defaults["access_token_secret"]
    )
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


def fetch_follower_ids(access_token: str) -> list[str]:
    follower_ids: list[str] = []
    cursor: str | None = None
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=20) as client:
        while True:
            params = {"limit": "1000"}
            if cursor:
                params["start"] = cursor
            response = client.get(FOLLOWERS_URL, headers=headers, params=params)
            if response.status_code == 403:
                raise RuntimeError(
                    "LINE Followers API returned 403. The OA must be verified or premium; "
                    "use the campaign LIFF friendship policy for existing followers instead."
                )
            response.raise_for_status()
            payload = response.json()
            page = payload.get("userIds")
            if not isinstance(page, list) or not all(isinstance(item, str) for item in page):
                raise RuntimeError("LINE Followers API returned an invalid response")
            follower_ids.extend(page)
            cursor = payload.get("next")
            if not isinstance(cursor, str) or not cursor:
                break
    return follower_ids


def write_followers(
    client: firestore.Client,
    *,
    follower_ids: list[str],
    channel_id: str,
    observed_at: datetime,
) -> None:
    for offset in range(0, len(follower_ids), MAX_BATCH_WRITES):
        batch = client.batch()
        for line_user_id in follower_ids[offset : offset + MAX_BATCH_WRITES]:
            document_id = friendship_document_id(line_user_id, channel_id)
            ref = client.collection("line_friendships").document(document_id)
            batch.set(
                ref,
                follower_sync_record(channel_id=channel_id, observed_at=observed_at),
                merge=True,
            )
        batch.commit()


def main() -> int:
    args = parse_args()
    access_token = access_secret(args.project, args.access_token_secret)
    channel_id = access_secret(args.project, args.channel_id_secret)
    follower_ids = fetch_follower_ids(access_token)
    print(f"Project: {args.project}")
    print(f"Database: {args.database}")
    print(f"Followers returned: {len(follower_ids)}")
    print("Raw LINE user IDs will not be stored or printed.")
    if not args.apply:
        print("Dry-run only. Add --apply and matching --confirm-database to write.")
        return 0
    observed_at = datetime.now(UTC)
    client = firestore.Client(project=args.project, database=args.database)
    write_followers(
        client,
        follower_ids=follower_ids,
        channel_id=channel_id,
        observed_at=observed_at,
    )
    run_ref = client.collection("line_friendship_sync_runs").document()
    run_ref.set(
        {
            "source": "LINE_FOLLOWERS_API",
            "environment": args.environment,
            "followerCount": len(follower_ids),
            "completedAt": observed_at,
        }
    )
    print(f"Backfill complete: {len(follower_ids)} friendship records merged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
