from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from app.core.errors import FinancialConflict
from app.core.settings import Settings
from app.core.types import BeamDeviceType, BeamPaymentMethod
from app.domains.payments.models import MoneyBreakdown, Payment, ServiceLineSnapshot
from app.integrations.beam import (
    BeamCharge,
    BeamClient,
    BeamConfigurationError,
    normalize_charge_action,
    validate_authoritative_charge,
    verify_beam_webhook_signature,
)


def payment() -> Payment:
    return Payment(
        payment_id="pay_001",
        booking_doc_id="booking_001",
        booking_public_id="BK-20260831-001",
        branch_id="branch_001",
        amounts=MoneyBreakdown(35_000, 5_000, 40_000),
        service_lines=(ServiceLineSnapshot("FOOT-60", "Foot massage", 1, 35_000),),
    )


def settings() -> Settings:
    return Settings(
        beam_enabled=True,
        beam_merchant_id="merchant-test",
        beam_api_key=SecretStr("api-key-test"),
        beam_webhook_hmac_key=SecretStr("a2V5"),
        beam_return_url="https://customer.invalid/payment/return",
    )


def test_beam_payment_method_allowlist_is_ordered_deduplicated_and_fail_closed() -> None:
    configured = settings().model_copy(
        update={"beam_payment_methods": "KPLUS,SCB_EASY,KPLUS,QR_PROMPT_PAY"}
    )
    assert configured.configured_beam_payment_methods == (
        BeamPaymentMethod.KPLUS,
        BeamPaymentMethod.SCB_EASY,
        BeamPaymentMethod.QR_PROMPT_PAY,
    )

    invalid = settings().model_copy(
        update={"beam_payment_methods": "KPLUS,UNSUPPORTED_BANK"}
    )
    assert "BEAM_PAYMENT_METHODS_INVALID" in invalid.beam_readiness_errors()


def test_production_mobile_banking_requires_explicit_method_and_webhook_confirmation() -> None:
    production = settings().model_copy(
        update={
            "app_env": "production",
            "beam_api_base_url": "https://api.beamcheckout.com",
            "beam_return_url": "https://spa-customer-web.example/my-bookings",
            "beam_payment_methods": "KPLUS,QR_PROMPT_PAY",
        }
    )

    assert "BEAM_PRODUCTION_MOBILE_BANKING_NOT_CONFIRMED" in (
        production.beam_readiness_errors()
    )
    assert "BEAM_PRODUCTION_WEBHOOK_NOT_CONFIRMED" in (
        production.beam_readiness_errors()
    )

    confirmed = production.model_copy(
        update={
            "beam_production_mobile_banking_confirmed": True,
            "beam_production_webhook_registered": True,
        }
    )
    assert confirmed.beam_readiness_errors() == ()


def test_production_beam_return_url_rejects_test_host() -> None:
    production = settings().model_copy(
        update={
            "app_env": "prod",
            "beam_api_base_url": "https://api.beamcheckout.com",
            "beam_return_url": "https://spa-customer-web-test.example/my-bookings",
            "beam_production_webhook_registered": True,
        }
    )

    assert "BEAM_PRODUCTION_RETURN_URL_INVALID" in production.beam_readiness_errors()


def test_webhook_signature_uses_raw_body_and_decoded_hmac_key() -> None:
    raw_body = b'{"chargeId":"ch_001","status":"SUCCEEDED"}'
    assert verify_beam_webhook_signature(
        raw_body,
        "vsLr2TuuxvCE5px4kin71NBT4C/oTunY8DpHMGBge7Y=",
        "a2V5",
    )
    assert not verify_beam_webhook_signature(raw_body + b"\n", "invalid", "a2V5")


def test_authoritative_lookup_requires_exact_merchant_reference_currency_and_amount() -> None:
    charge = BeamCharge(
        charge_id="ch_001",
        merchant_id="merchant-test",
        reference_id="SPA-PAY-pay_001",
        status="SUCCEEDED",
        currency="THB",
        amount=40_000,
        transaction_time=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
    )
    assert validate_authoritative_charge(
        charge,
        payment(),
        expected_merchant_id="merchant-test",
        expected_reference_id="SPA-PAY-pay_001",
        attempt_created_at=datetime(2026, 8, 31, 11, 45, tzinfo=UTC),
        attempt_expires_at=datetime(2026, 8, 31, 12, 15, tzinfo=UTC),
    ) == datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    with pytest.raises(FinancialConflict, match="amount"):
        validate_authoritative_charge(
            replace(charge, amount=39_999),
            payment(),
            expected_merchant_id="merchant-test",
            expected_reference_id="SPA-PAY-pay_001",
            attempt_created_at=datetime(2026, 8, 31, 11, 45, tzinfo=UTC),
            attempt_expires_at=datetime(2026, 8, 31, 12, 15, tzinfo=UTC),
        )


def test_authoritative_lookup_rejects_success_outside_attempt_window() -> None:
    charge = BeamCharge(
        charge_id="ch_001",
        merchant_id="merchant-test",
        reference_id="SPA-PAY-pay_001",
        status="SUCCEEDED",
        currency="THB",
        amount=40_000,
        transaction_time=datetime(2026, 8, 31, 12, 16, tzinfo=UTC),
    )
    with pytest.raises(FinancialConflict, match="attempt window"):
        validate_authoritative_charge(
            charge,
            payment(),
            expected_merchant_id="merchant-test",
            expected_reference_id="SPA-PAY-pay_001",
            attempt_created_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
            attempt_expires_at=datetime(2026, 8, 31, 12, 15, tzinfo=UTC),
        )


def test_qr_action_is_reduced_to_browser_safe_fields() -> None:
    action = normalize_charge_action(
        {
            "chargeId": "ch_001",
            "actionRequired": "ENCODED_IMAGE",
            "paymentMethodType": "QR_PROMPT_PAY",
            "encodedImage": {
                "expiry": "2026-08-31T15:15:00+07:00",
                "imageBase64Encoded": "iVBORw0KGgo=",
                "rawData": "must-not-be-forwarded",
            },
            "providerInternal": {"secret": True},
        }
    )
    assert action.charge_id == "ch_001"
    assert action.image_base64 == "iVBORw0KGgo="
    assert not hasattr(action, "raw_data")


def test_qr_action_uses_requested_expiry_when_playground_returns_null() -> None:
    requested_expiry = datetime(2026, 8, 31, 15, 15, tzinfo=UTC)
    action = normalize_charge_action(
        {
            "chargeId": "ch_001",
            "actionRequired": "ENCODED_IMAGE",
            "paymentMethodType": "QR_PROMPT_PAY",
            "encodedImage": {
                "expiry": None,
                "imageBase64Encoded": "iVBORw0KGgo=",
            },
        },
        requested_expires_at=requested_expiry,
    )
    assert action.expires_at == requested_expiry


def test_qr_action_requires_provider_or_requested_expiry() -> None:
    with pytest.raises(BeamConfigurationError, match="missing expiry"):
        normalize_charge_action(
            {
                "chargeId": "ch_001",
                "actionRequired": "ENCODED_IMAGE",
                "paymentMethodType": "QR_PROMPT_PAY",
                "encodedImage": {
                    "expiry": None,
                    "imageBase64Encoded": "iVBORw0KGgo=",
                },
            }
        )


@pytest.mark.asyncio
async def test_qr_charge_uses_satang_and_idempotency_header() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(201, json={"chargeId": "ch_001", "status": "PENDING"})

    async with BeamClient(settings(), httpx.MockTransport(handler)) as client:
        result = await client.create_qr_promptpay_charge(
            amount_satang=40_000,
            reference_id="SPA-PAY-pay_001",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            idempotency_key="attempt_001",
        )

    assert result["chargeId"] == "ch_001"
    assert captured is not None
    assert captured.headers["x-beam-idempotency-key"] == "attempt_001"
    assert b'"amount":40000' in captured.content
    assert b'"paymentMethodType":"QR_PROMPT_PAY"' in captured.content


@pytest.mark.parametrize(
    ("method", "provider_field"),
    [
        (BeamPaymentMethod.KPLUS, b'"kPlus":{}'),
        (BeamPaymentMethod.SCB_EASY, b'"scbEasy":{}'),
        (BeamPaymentMethod.KRUNGSRI_APP, b'"krungsri":{}'),
        (BeamPaymentMethod.BANGKOK_BANK_APP, b'"bbl":{}'),
    ],
)
@pytest.mark.asyncio
async def test_mobile_banking_charge_uses_method_device_and_idempotency(
    method: BeamPaymentMethod,
    provider_field: bytes,
) -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            201,
            json={
                "chargeId": "ch_mobile_001",
                "paymentMethodType": method.value,
                "actionRequired": "REDIRECT",
                "redirect": {"redirectUrl": "https://checkout.beamcheckout.com/test"},
            },
        )

    async with BeamClient(settings(), httpx.MockTransport(handler)) as client:
        result = await client.create_mobile_banking_charge(
            amount_satang=40_000,
            reference_id="SPA-PAY-pay_001",
            payment_method=method,
            device_type=BeamDeviceType.IOS,
            idempotency_key="attempt_mobile_001",
        )

    assert result["chargeId"] == "ch_mobile_001"
    assert captured is not None
    assert captured.headers["x-beam-idempotency-key"] == "attempt_mobile_001"
    assert b'"deviceType":"IOS"' in captured.content
    assert f'"paymentMethodType":"{method.value}"'.encode() in captured.content
    assert provider_field in captured.content


def test_mobile_banking_redirect_is_reduced_to_allowlisted_browser_fields() -> None:
    action = normalize_charge_action(
        {
            "chargeId": "ch_mobile_001",
            "paymentMethodType": "KPLUS",
            "actionRequired": "REDIRECT",
            "redirect": {"redirectUrl": "https://checkout.beamcheckout.com/test"},
            "providerInternal": {"secret": True},
        },
        requested_method=BeamPaymentMethod.KPLUS,
    )

    assert action.payment_method is BeamPaymentMethod.KPLUS
    assert action.redirect_url == "https://checkout.beamcheckout.com/test"
    assert action.image_base64 is None


@pytest.mark.parametrize(
    "method",
    [BeamPaymentMethod.KPLUS, BeamPaymentMethod.SCB_EASY],
)
def test_mobile_banking_playground_encoded_image_is_accepted(
    method: BeamPaymentMethod,
) -> None:
    requested_expiry = datetime(2026, 9, 1, 6, 18, tzinfo=UTC)
    action = normalize_charge_action(
        {
            "chargeId": "ch_mobile_playground_001",
            "paymentMethodType": method.value,
            "actionRequired": "ENCODED_IMAGE",
            "encodedImage": {
                "expiry": None,
                "imageBase64Encoded": "iVBORw0KGgo=",
                "rawData": "must-not-be-forwarded",
            },
        },
        requested_method=method,
        requested_expires_at=requested_expiry,
    )

    assert action.payment_method is method
    assert action.action_required == "ENCODED_IMAGE"
    assert action.image_base64 == "iVBORw0KGgo="
    assert action.expires_at == requested_expiry
    assert action.redirect_url is None


def test_mobile_banking_no_action_is_accepted_without_provider_fields() -> None:
    action = normalize_charge_action(
        {
            "chargeId": "ch_mobile_none_001",
            "paymentMethodType": "KRUNGSRI_APP",
            "actionRequired": "NONE",
        },
        requested_method=BeamPaymentMethod.KRUNGSRI_APP,
    )

    assert action.action_required == "NONE"
    assert action.image_base64 is None
    assert action.redirect_url is None


def test_charge_action_rejects_payment_method_mismatch() -> None:
    with pytest.raises(BeamConfigurationError, match="does not match"):
        normalize_charge_action(
            {
                "chargeId": "ch_mobile_001",
                "paymentMethodType": "SCB_EASY",
                "actionRequired": "NONE",
            },
            requested_method=BeamPaymentMethod.KPLUS,
        )


def test_mobile_banking_redirect_rejects_non_beam_host() -> None:
    with pytest.raises(BeamConfigurationError, match="allowlisted"):
        normalize_charge_action(
            {
                "chargeId": "ch_mobile_001",
                "paymentMethodType": "SCB_EASY",
                "actionRequired": "REDIRECT",
                "redirect": {"redirectUrl": "https://attacker.invalid/collect"},
            },
            requested_method=BeamPaymentMethod.SCB_EASY,
        )


@pytest.mark.asyncio
async def test_list_charges_filters_by_exact_reference() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "chargeId": "ch_001",
                        "merchantId": "merchant-test",
                        "referenceId": "SPA-PAY-pay_001-pat_001",
                        "status": "FAILED",
                        "currency": "THB",
                        "amount": 40_000,
                        "transactionTime": None,
                        "failureCode": "CH_PROCESSING_FAILED",
                    }
                ],
                "totalCount": 1,
            },
        )

    async with BeamClient(settings(), httpx.MockTransport(handler)) as client:
        result = await client.list_charges_by_reference("SPA-PAY-pay_001-pat_001")

    assert captured is not None
    assert captured.url.params["referenceId"] == "SPA-PAY-pay_001-pat_001"
    assert captured.url.params["limit"] == "2"
    assert result.total_count == 1
    assert result.charges[0].failure_code == "CH_PROCESSING_FAILED"


@pytest.mark.asyncio
async def test_list_charges_rejects_provider_reference_mismatch() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "chargeId": "ch_001",
                        "merchantId": "merchant-test",
                        "referenceId": "another-reference",
                        "status": "FAILED",
                        "currency": "THB",
                        "amount": 40_000,
                    }
                ],
                "totalCount": 1,
            },
        )

    async with BeamClient(settings(), httpx.MockTransport(handler)) as client:
        with pytest.raises(BeamConfigurationError, match="reference"):
            await client.list_charges_by_reference("SPA-PAY-pay_001-pat_001")
