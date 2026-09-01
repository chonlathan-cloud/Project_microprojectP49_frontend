from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest, digest
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.errors import FinancialConflict, FinancialInvariantError
from app.core.settings import Settings
from app.core.types import BeamDeviceType, BeamPaymentMethod
from app.domains.payments.models import Payment


class BeamError(Exception):
    pass


class BeamConfigurationError(BeamError):
    pass


class BeamRetryableError(BeamError):
    pass


class BeamRejectedError(BeamError):
    pass


class BeamAmbiguousCreateError(BeamError):
    pass


@dataclass(frozen=True, slots=True)
class BeamAction:
    charge_id: str
    payment_method: BeamPaymentMethod
    action_required: str
    expires_at: datetime | None
    image_base64: str | None = None
    redirect_url: str | None = None


def normalize_charge_action(
    payload: dict[str, Any],
    *,
    requested_method: BeamPaymentMethod = BeamPaymentMethod.QR_PROMPT_PAY,
    requested_expires_at: datetime | None = None,
) -> BeamAction:
    """Return the small provider action contract that is safe for the browser."""
    charge_id = payload.get("chargeId")
    action_required = payload.get("actionRequired")
    if not isinstance(charge_id, str) or not charge_id:
        raise BeamConfigurationError("Beam charge response is missing chargeId")
    if action_required not in {"NONE", "REDIRECT", "ENCODED_IMAGE"}:
        raise BeamConfigurationError("Beam charge response has an unsupported action")
    try:
        response_method = BeamPaymentMethod(str(payload.get("paymentMethodType", "")))
    except ValueError as error:
        raise BeamConfigurationError("Beam charge response is missing paymentMethodType") from error
    if response_method is not requested_method:
        raise BeamConfigurationError("Beam charge response payment method does not match request")
    expected_action = (
        "ENCODED_IMAGE"
        if requested_method is BeamPaymentMethod.QR_PROMPT_PAY
        else "REDIRECT"
    )
    if action_required != expected_action:
        raise BeamConfigurationError("Beam charge response action does not match payment method")

    expires_at: datetime | None = None
    image_base64: str | None = None
    redirect_url: str | None = None
    if action_required == "ENCODED_IMAGE":
        encoded = payload.get("encodedImage")
        if not isinstance(encoded, dict):
            raise BeamConfigurationError("Beam QR response is missing encodedImage")
        image_base64 = encoded.get("imageBase64Encoded")
        expiry = encoded.get("expiry")
        if not isinstance(image_base64, str) or not image_base64:
            raise BeamConfigurationError("Beam QR response is missing image data")
        if len(image_base64) > 2_000_000:
            raise BeamConfigurationError("Beam QR response image is too large")
        if expiry is None:
            expires_at = requested_expires_at
        elif isinstance(expiry, str) and expiry:
            try:
                expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            except ValueError as error:
                raise BeamConfigurationError("Beam QR response expiry is invalid") from error
        else:
            raise BeamConfigurationError("Beam QR response expiry is invalid")
        if expires_at is None:
            raise BeamConfigurationError("Beam QR response is missing expiry")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise BeamConfigurationError("Beam QR response expiry must include timezone")
    elif action_required == "REDIRECT":
        redirect = payload.get("redirect")
        redirect_url = redirect.get("redirectUrl") if isinstance(redirect, dict) else None
        if not isinstance(redirect_url, str) or not redirect_url.startswith("https://"):
            raise BeamConfigurationError("Beam redirect URL is invalid")
        allowed_hosts = (".beamcheckout.com", ".beamcheckout.co")
        hostname = urlparse(redirect_url).hostname or ""
        if hostname not in {"beamcheckout.com", "beamcheckout.co"} and not hostname.endswith(
            allowed_hosts
        ):
            raise BeamConfigurationError("Beam redirect URL host is not allowlisted")

    return BeamAction(
        charge_id=charge_id,
        payment_method=response_method,
        action_required=action_required,
        expires_at=expires_at,
        image_base64=image_base64,
        redirect_url=redirect_url,
    )


@dataclass(frozen=True, slots=True)
class BeamCharge:
    charge_id: str
    merchant_id: str
    reference_id: str
    status: str
    currency: str
    amount: int
    transaction_time: datetime | None
    failure_code: str | None = None

    @classmethod
    def from_provider(cls, payload: dict[str, Any]) -> "BeamCharge":
        transaction_time = payload.get("transactionTime")
        return cls(
            charge_id=str(payload.get("chargeId", "")),
            merchant_id=str(payload.get("merchantId", "")),
            reference_id=str(payload.get("referenceId", "")),
            status=str(payload.get("status", "")),
            currency=str(payload.get("currency", "")),
            amount=payload.get("amount", 0),
            transaction_time=(
                datetime.fromisoformat(transaction_time.replace("Z", "+00:00"))
                if isinstance(transaction_time, str) and transaction_time
                else None
            ),
            failure_code=payload.get("failureCode"),
        )


@dataclass(frozen=True, slots=True)
class BeamChargeList:
    charges: tuple[BeamCharge, ...]
    total_count: int


def verify_beam_webhook_signature(raw_body: bytes, signature: str, encoded_key: str) -> bool:
    try:
        key = b64decode(encoded_key, validate=True)
        supplied = b64decode(signature, validate=True)
    except (ValueError, TypeError):
        return False
    expected = digest(key, raw_body, sha256)
    return compare_digest(expected, supplied)


def validate_authoritative_charge(
    charge: BeamCharge,
    payment: Payment,
    *,
    expected_merchant_id: str,
    expected_reference_id: str,
    attempt_created_at: datetime,
    attempt_expires_at: datetime,
) -> datetime:
    if charge.status != "SUCCEEDED" or charge.transaction_time is None:
        raise FinancialConflict("Beam charge is not an authoritative success")
    if charge.merchant_id != expected_merchant_id:
        raise FinancialConflict("Beam merchant does not match configured merchant")
    if charge.reference_id != expected_reference_id:
        raise FinancialConflict("Beam reference does not match payment attempt")
    if charge.currency != payment.amounts.currency:
        raise FinancialConflict("Beam currency does not match payment")
    if isinstance(charge.amount, bool) or not isinstance(charge.amount, int):
        raise FinancialInvariantError("Beam amount must be integer satang")
    if charge.amount != payment.amounts.gross_amount_satang:
        raise FinancialConflict("Beam amount does not match payment snapshot")
    if (
        attempt_created_at.tzinfo is None
        or attempt_created_at.utcoffset() is None
        or attempt_expires_at.tzinfo is None
        or attempt_expires_at.utcoffset() is None
    ):
        raise FinancialInvariantError("Payment attempt window must be timezone-aware")
    if not attempt_created_at <= charge.transaction_time <= attempt_expires_at:
        raise FinancialConflict("Beam transaction time is outside the payment attempt window")
    return charge.transaction_time


class BeamClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if settings.beam_readiness_errors():
            raise BeamConfigurationError(
                f"Beam integration is not ready: {settings.beam_readiness_errors()}"
            )
        self._settings = settings
        if settings.beam_merchant_id is None or settings.beam_api_key is None:
            raise BeamConfigurationError("Beam server credentials are required")
        self._client = httpx.AsyncClient(
            base_url=settings.beam_api_base_url,
            auth=httpx.BasicAuth(
                settings.beam_merchant_id,
                settings.beam_api_key.get_secret_value(),
            ),
            timeout=settings.beam_request_timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> "BeamClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_qr_promptpay_charge(
        self,
        *,
        amount_satang: int,
        reference_id: str,
        expires_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if amount_satang <= 0:
            raise FinancialInvariantError("Beam charge amount must be positive")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise FinancialInvariantError("Beam charge expiry must be timezone-aware")
        payload = {
            "amount": amount_satang,
            "currency": "THB",
            "paymentMethod": {
                "qrPromptPay": {"expiryTime": expires_at.isoformat()},
                "paymentMethodType": "QR_PROMPT_PAY",
            },
            "referenceId": reference_id,
            "returnUrl": self._settings.beam_return_url,
        }
        return await self._request(
            "POST",
            "/api/v1/charges",
            json=payload,
            headers={"x-beam-idempotency-key": idempotency_key},
            create_request=True,
        )

    async def create_mobile_banking_charge(
        self,
        *,
        amount_satang: int,
        reference_id: str,
        payment_method: BeamPaymentMethod,
        device_type: BeamDeviceType,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if amount_satang <= 0:
            raise FinancialInvariantError("Beam charge amount must be positive")
        if payment_method is BeamPaymentMethod.QR_PROMPT_PAY:
            raise FinancialInvariantError("PromptPay must use the QR charge flow")
        if device_type is BeamDeviceType.WEB:
            raise FinancialInvariantError("Mobile banking requires an iOS or Android device")
        method_fields = {
            BeamPaymentMethod.KPLUS: "kPlus",
            BeamPaymentMethod.SCB_EASY: "scbEasy",
            BeamPaymentMethod.KRUNGSRI_APP: "krungsri",
            BeamPaymentMethod.BANGKOK_BANK_APP: "bbl",
        }
        method_field = method_fields.get(payment_method)
        if method_field is None:
            raise FinancialInvariantError("Unsupported Beam mobile-banking method")
        payload = {
            "amount": amount_satang,
            "currency": "THB",
            "paymentMethod": {
                method_field: {},
                "paymentMethodType": payment_method.value,
            },
            "deviceType": device_type.value,
            "referenceId": reference_id,
            "returnUrl": self._settings.beam_return_url,
        }
        return await self._request(
            "POST",
            "/api/v1/charges",
            json=payload,
            headers={"x-beam-idempotency-key": idempotency_key},
            create_request=True,
        )

    async def get_charge(self, charge_id: str) -> BeamCharge:
        payload = await self._request("GET", f"/api/v1/charges/{charge_id}")
        return BeamCharge.from_provider(payload)

    async def list_charges_by_reference(
        self,
        reference_id: str,
        *,
        limit: int = 2,
    ) -> BeamChargeList:
        if not reference_id or len(reference_id) > 200:
            raise FinancialInvariantError("Beam referenceId is invalid")
        if not 1 <= limit <= 20:
            raise FinancialInvariantError("Beam charge list limit is invalid")
        payload = await self._request(
            "GET",
            "/api/v1/charges",
            params={"referenceId": reference_id, "limit": limit},
        )
        raw_charges = payload.get("data")
        total_count = payload.get("totalCount")
        if (
            not isinstance(raw_charges, list)
            or isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count < len(raw_charges)
        ):
            raise BeamConfigurationError("Beam charge list response is invalid")
        charges: list[BeamCharge] = []
        for item in raw_charges:
            if not isinstance(item, dict):
                raise BeamConfigurationError("Beam charge list item is invalid")
            charge = BeamCharge.from_provider(item)
            if charge.reference_id != reference_id:
                raise BeamConfigurationError("Beam charge list reference does not match filter")
            charges.append(charge)
        return BeamChargeList(tuple(charges), total_count)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        create_request: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            if create_request:
                raise BeamAmbiguousCreateError(
                    "Beam create outcome is unknown; reconcile with the same idempotency key"
                ) from error
            raise BeamRetryableError("Beam request failed before a response") from error
        if response.status_code == 429 or response.status_code >= 500:
            raise BeamRetryableError(f"Beam request failed with {response.status_code}")
        if response.status_code >= 400:
            raise BeamRejectedError(f"Beam rejected request with {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise BeamConfigurationError("Beam returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise BeamConfigurationError("Beam returned an invalid response")
        return payload
