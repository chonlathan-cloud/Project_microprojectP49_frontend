from __future__ import annotations

from datetime import UTC, datetime

from google.cloud import firestore

from app.integrations.line_identity import line_identity_hash


def friendship_document_id(line_user_id: str, channel_id: str) -> str:
    return line_identity_hash(line_user_id, channel_id)


def webhook_friendship_record(
    *, channel_id: str, friend_status: str, observed_at: datetime
) -> dict[str, object]:
    record: dict[str, object] = {
        "provider": "LINE",
        "channelId": channel_id,
        "status": friend_status,
        "evidenceSource": "WEBHOOK",
        "assurance": "SERVER_VERIFIED",
        "lastObservedAt": observed_at,
        "updatedAt": observed_at,
    }
    if friend_status == "FOLLOWING":
        record["followedAt"] = observed_at
    else:
        record["blockedAt"] = observed_at
    return record


def client_attested_friendship_record(
    *, channel_id: str, observed_at: datetime | None = None
) -> dict[str, object]:
    current_time = observed_at or datetime.now(UTC)
    return {
        "provider": "LINE",
        "channelId": channel_id,
        "status": "REPORTED_FOLLOWING",
        "evidenceSource": "LIFF_CLIENT",
        "assurance": "CLIENT_ATTESTED",
        "lastObservedAt": current_time,
        "updatedAt": current_time,
    }


def follower_sync_record(
    *, channel_id: str, observed_at: datetime | None = None
) -> dict[str, object]:
    current_time = observed_at or datetime.now(UTC)
    return {
        "provider": "LINE",
        "channelId": channel_id,
        "status": "FOLLOWING",
        "evidenceSource": "FOLLOWER_SYNC",
        "assurance": "SERVER_VERIFIED",
        "lastObservedAt": current_time,
        "updatedAt": current_time,
    }


def friendship_ref(
    client: firestore.Client, *, line_user_id: str, channel_id: str
):
    return client.collection("line_friendships").document(
        friendship_document_id(line_user_id, channel_id)
    )
