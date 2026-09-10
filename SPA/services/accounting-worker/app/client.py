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
            try:
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
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                raise FlowAccountRetryableError(
                    "FlowAccount authentication is unavailable"
                ) from error
            if response.status_code >= 500 or response.status_code == 429:
                raise FlowAccountRetryableError(f"Token request failed with {response.status_code}")
            if response.status_code >= 400:
                raise FlowAccountConfigurationError(
                    f"Token request failed with {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as error:
                raise FlowAccountConfigurationError(
                    "Token response is not valid JSON"
                ) from error
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
            try:
                body = response.json()
            except ValueError as error:
                raise FlowAccountAmbiguousCreateError(
                    "FlowAccount create response is invalid and requires reconciliation"
                ) from error
            if not isinstance(body, dict):
                raise FlowAccountConfigurationError("FlowAccount returned an invalid response")
            if body.get("status") is False:
                raise FlowAccountConfigurationError("FlowAccount rejected the document contract")
            data = body.get("data")
            if not isinstance(data, dict):
                raise FlowAccountAmbiguousCreateError(
                    "FlowAccount create response data requires reconciliation"
                )
            return data
        raise FlowAccountConfigurationError("FlowAccount authentication failed after refresh")

    async def _authorized_get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        for auth_attempt in range(2):
            token = await self._access_token(force_refresh=auth_attempt == 1)
            try:
                response = await self._client.get(
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                raise FlowAccountRetryableError(
                    "FlowAccount configuration validation is unavailable"
                ) from error
            if response.status_code == 401 and auth_attempt == 0:
                self._token = None
                continue
            if response.status_code == 429 or response.status_code >= 500:
                raise FlowAccountRetryableError(
                    f"FlowAccount validation failed with {response.status_code}"
                )
            if response.status_code >= 400:
                raise FlowAccountConfigurationError(
                    f"FlowAccount validation was rejected with {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as error:
                raise FlowAccountConfigurationError(
                    "FlowAccount validation response is not valid JSON"
                ) from error
            if not isinstance(body, dict) or body.get("status") is False:
                raise FlowAccountConfigurationError(
                    "FlowAccount validation response is invalid"
                )
            return body.get("data")
        raise FlowAccountConfigurationError("FlowAccount authentication failed after refresh")

    async def validate_configuration(self) -> None:
        company = await self._authorized_get(self._settings.company_info_path)
        if not isinstance(company, dict):
            raise FlowAccountConfigurationError("FlowAccount company response is invalid")
        names = {
            str(company.get(field, "")).strip().casefold()
            for field in ("compnayName", "companyName", "companyNameEn")
            if company.get(field)
        }
        if self._settings.expected_company_name.strip().casefold() not in names:
            raise FlowAccountConfigurationError("FlowAccount company identity does not match")
        if str(company.get("companyType", "")) not in {"10", "40", "50"}:
            raise FlowAccountConfigurationError("FlowAccount company is not VAT registered")

        contact = await self._authorized_get(
            self._settings.contact_path_template.replace(
                "{contactId}", self._settings.contact_id or ""
            )
        )
        if isinstance(contact, dict) and isinstance(contact.get("list"), list):
            contact = next(
                (
                    item
                    for item in contact["list"]
                    if isinstance(item, dict)
                    and str(item.get("id", "")) == self._settings.contact_id
                ),
                None,
            )
        if not isinstance(contact, dict):
            raise FlowAccountConfigurationError("FlowAccount contact response is invalid")
        if (
            str(contact.get("id", "")) != self._settings.contact_id
            or str(contact.get("contactCode", "")) != self._settings.contact_code
            or str(contact.get("contactName", "")) != self._settings.contact_name
        ):
            raise FlowAccountConfigurationError("FlowAccount walk-in contact does not match")

        channels = await self._authorized_get(self._settings.other_channels_path)
        if not isinstance(channels, list):
            raise FlowAccountConfigurationError("FlowAccount channel response is invalid")
        matches = [
            channel
            for channel in channels
            if isinstance(channel, dict)
            and str(channel.get("otherChannelsId", "")) == self._settings.other_channel_id
            and str(channel.get("otherChannelsName", ""))
            == self._settings.other_channel_name
        ]
        if len(matches) != 1:
            raise FlowAccountConfigurationError("FlowAccount Other Channel does not match")

        configured_accounts = self._settings.configured_bank_transfer_accounts
        if configured_accounts:
            bank_accounts = await self._authorized_get(self._settings.bank_accounts_path)
            if not isinstance(bank_accounts, list):
                raise FlowAccountConfigurationError("FlowAccount bank-account response is invalid")
            for configured in configured_accounts:
                bank_matches = [
                    account
                    for account in bank_accounts
                    if isinstance(account, dict)
                    and str(account.get("bankAccountId", ""))
                    == configured.bank_account_id
                    and str(account.get("bankId", ""))
                    == configured.transfer_bank_account_id
                ]
                if len(bank_matches) != 1:
                    raise FlowAccountConfigurationError(
                        "FlowAccount bank account does not match"
                    )

    async def find_cash_invoices(
        self, *, external_document_id: str, accounting_date: str
    ) -> tuple[dict[str, Any], ...]:
        matches: list[dict[str, Any]] = []
        for current_page in range(1, 21):
            body = await self._authorized_get(
                self._settings.cash_invoice_list_path,
                params={
                    "currentPage": current_page,
                    "pageSize": 100,
                    "range": 5,
                    "startDate": accounting_date,
                    "endDate": accounting_date,
                },
            )
            records = body.get("list") if isinstance(body, dict) else None
            total_value = (
                body.get("totalDocument", body.get("total"))
                if isinstance(body, dict)
                else None
            )
            try:
                total = int(total_value)
            except (TypeError, ValueError):
                total = -1
            if (
                not isinstance(records, list)
                or isinstance(total_value, bool)
                or total < 0
            ):
                raise FlowAccountConfigurationError(
                    "FlowAccount reconciliation response is invalid"
                )
            matches.extend(
                record
                for record in records
                if isinstance(record, dict)
                and str(record.get("externalDocumentId", ""))
                == external_document_id
            )
            if current_page * 100 >= total:
                return tuple(matches)
        raise FlowAccountRetryableError(
            "FlowAccount reconciliation result exceeds the bounded scan"
        )
