import asyncio
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from app.settings import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


def _verify(token: str, audience: str) -> dict[str, Any]:
    claims = id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)
    return claims if isinstance(claims, dict) else {}


async def require_task_invoker(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC bearer is required")
    if not settings.oidc_audience or not settings.invoker_emails:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC is not configured")
    try:
        claims = await asyncio.to_thread(_verify, credentials.credentials, settings.oidc_audience)
    except (GoogleAuthError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC bearer is invalid") from None
    email = claims.get("email")
    if (
        not isinstance(email, str)
        or claims.get("email_verified") is not True
        or email.lower() not in settings.invoker_emails
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "OIDC principal is not allowed")
    return email.lower()
