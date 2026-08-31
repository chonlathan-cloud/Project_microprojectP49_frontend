import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.settings import Settings


class FlowAccountError(Exception):
    pass


class FlowAccountConfigurationError(FlowAccountError):
    pass


class FlowAccountRetryableError(FlowAccountError):
    pass


class FlowAccountAmbiguousCreateError(FlowAccountError):
    pass


@dataclass(frozen=True, slots=True)
class Token:
    value: str
    expires_at: datetime


class FlowAccountClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.api_base_url:
            raise FlowAccountConfigurationError("FlowAccount API base URL is not configured")
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=settings.request_timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._token: Token | None = None
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "FlowAccountClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _access_token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            now = datetime.now(UTC)
            if (
                not force_refresh
                and self._token is not None
                and self._token.expires_at > now + timedelta(seconds=60)
            ):
                return self._token.value
            if not self._settings.ready_for_sync:
                raise FlowAccountConfigurationError(
                    f"FlowAccount integration is not ready: {self._settings.readiness_errors()}"
                )
            response = await self._client.post(
                self._settings.token_path,
                data={
                    "grant_type": "client_credentials",
                    "scope": "flowaccount-api",
                    "client_id": self._settings.client_id.get_secret_value(),
                    "client_secret": self._settings.client_secret.get_secret_value(),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code >= 500 or response.status_code == 429:
                raise FlowAccountRetryableError(f"Token request failed with {response.status_code}")
            if response.status_code >= 400:
                raise FlowAccountConfigurationError(
                    f"Token request failed with {response.status_code}"
                )
            body = response.json()
            access_token = body.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise FlowAccountConfigurationError("Token response did not include access_token")
            expires_in = int(body.get("expires_in", 3600))
            self._token = Token(access_token, now + timedelta(seconds=max(expires_in, 60)))
            return access_token

    async def create_cash_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        for auth_attempt in range(2):
            token = await self._access_token(force_refresh=auth_attempt == 1)
            try:
                response = await self._client.post(
                    self._settings.cash_invoice_with_payment_path,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                raise FlowAccountAmbiguousCreateError(
                    "FlowAccount create outcome is unknown and requires reconciliation"
                ) from error

            if response.status_code == 401 and auth_attempt == 0:
                self._token = None
                continue
            if response.status_code == 429:
                raise FlowAccountRetryableError(
                    f"FlowAccount create failed with {response.status_code}"
                )
            if response.status_code >= 500:
                raise FlowAccountAmbiguousCreateError(
                    "FlowAccount create returned a server error and requires reconciliation"
                )
            if response.status_code >= 400:
                raise FlowAccountConfigurationError(
                    f"FlowAccount rejected the document with {response.status_code}"
                )
            body = response.json()
            if not isinstance(body, dict):
                raise FlowAccountConfigurationError("FlowAccount returned an invalid response")
            return body
        raise FlowAccountConfigurationError("FlowAccount authentication failed after refresh")
