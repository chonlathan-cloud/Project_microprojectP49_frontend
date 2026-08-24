from __future__ import annotations

import hashlib

import httpx

from app.core.errors import ValidationDomainError
from app.core.settings import get_settings


def line_identity_hash(line_user_id: str, channel_id: str | None = None) -> str:
    resolved_channel_id = channel_id or get_settings().line_customer_login_channel_id
    return hashlib.sha256(f"LINE:{resolved_channel_id}:{line_user_id}".encode()).hexdigest()


def verify_line_id_token(id_token: str) -> dict[str, object]:
    channel_id = get_settings().line_customer_login_channel_id
    if not channel_id:
        raise ValidationDomainError("LINE account linking is not configured")
    try:
        response = httpx.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": channel_id},
            timeout=10,
        )
    except httpx.HTTPError as error:
        raise ValidationDomainError(
            "LINE identity verification is temporarily unavailable"
        ) from error
    if response.status_code != 200:
        raise ValidationDomainError("LINE identity token is invalid or expired")
    payload = response.json()
    if str(payload.get("aud", "")) != channel_id or not payload.get("sub"):
        raise ValidationDomainError("LINE identity token has an invalid audience")
    return payload
