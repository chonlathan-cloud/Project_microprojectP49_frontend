import httpx
import pytest
from pydantic import SecretStr

from app.client import (
    FlowAccountAmbiguousCreateError,
    FlowAccountClient,
    FlowAccountConfigurationError,
)
from app.settings import Settings


def settings() -> Settings:
    return Settings(
        sync_enabled=True,
        sandbox_contract_proven=True,
        api_base_url="https://flowaccount.invalid",
        client_id=SecretStr("test-client"),
        client_secret=SecretStr("test-secret"),
        contact_id="1001",
        other_channel_id="2001",
        sell_chart_of_account_code="41110",
    )


@pytest.mark.asyncio
async def test_client_refreshes_token_once_after_401() -> None:
    token_calls = 0
    create_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, create_calls
        if request.url.path == "/token":
            token_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{token_calls}"})
        create_calls += 1
        if create_calls == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(
            201,
            json={"status": True, "data": {"recordId": "record-001"}},
        )

    async with FlowAccountClient(settings(), httpx.MockTransport(handler)) as client:
        result = await client.create_cash_invoice({"reference": "SPA-PAY-pay_001"})

    assert result["recordId"] == "record-001"
    assert token_calls == 2
    assert create_calls == 2


@pytest.mark.asyncio
async def test_network_error_after_create_is_ambiguous_not_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "token"})
        raise httpx.ReadTimeout("unknown create outcome", request=request)

    async with FlowAccountClient(settings(), httpx.MockTransport(handler)) as client:
        with pytest.raises(FlowAccountAmbiguousCreateError, match="reconciliation"):
            await client.create_cash_invoice({"reference": "SPA-PAY-pay_001"})


@pytest.mark.asyncio
async def test_server_error_after_create_is_ambiguous_not_blindly_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(500, json={"error": "unknown"})

    async with FlowAccountClient(settings(), httpx.MockTransport(handler)) as client:
        with pytest.raises(FlowAccountAmbiguousCreateError, match="reconciliation"):
            await client.create_cash_invoice({"reference": "SPA-PAY-pay_001"})


@pytest.mark.asyncio
async def test_configuration_validation_checks_company_contact_and_channel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "token"})
        if request.url.path == "/company/info":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {"companyNameEn": "Manee and Son Limited", "companyType": 10},
                },
            )
        if request.url.path == "/contacts/1001":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "id": 1001,
                        "contactCode": "SPA49-WALKIN",
                        "contactName": "ลูกค้าทั่วไป - SPA 49",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "status": True,
                "data": [
                    {
                        "otherChannelsId": "2001",
                        "otherChannelsName": "Beam/UOB Gateway - SPA 49",
                    }
                ],
            },
        )

    async with FlowAccountClient(settings(), httpx.MockTransport(handler)) as client:
        await client.validate_configuration()


@pytest.mark.asyncio
async def test_configuration_validation_rejects_wrong_company() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"status": True, "data": {"companyNameEn": "Wrong Company", "companyType": 10}},
        )

    async with FlowAccountClient(settings(), httpx.MockTransport(handler)) as client:
        with pytest.raises(FlowAccountConfigurationError, match="identity"):
            await client.validate_configuration()
