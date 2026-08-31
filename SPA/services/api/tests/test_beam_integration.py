from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from app.core.errors import FinancialConflict
from app.core.settings import Settings
from app.domains.payments.models import MoneyBreakdown, Payment, ServiceLineSnapshot
from app.integrations.beam import (
    BeamCharge,
    BeamClient,
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
