import json
from datetime import datetime
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.application.payments import PaymentService, PaymentStatusResult
from app.core.auth import require_admin_user
from app.core.errors import AuthenticationInvalid, ValidationDomainError
from app.core.settings import get_settings
from app.core.types import (
    AppRole,
    BeamDeviceType,
    BeamPaymentMethod,
    PaymentSource,
    PaymentStatus,
)
from app.domains.identity.models import AdminPrincipal, LinePrincipal
from app.infrastructure.firestore_payments import FirestorePaymentRepository
from app.integrations.beam import verify_beam_webhook_signature
from app.integrations.line_identity import verify_line_id_token

public_router = APIRouter(prefix="/api/v1/public", tags=["public-payments"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin-payments"])
webhook_router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class StrictModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )


@lru_cache
def _payment_service() -> PaymentService:
    settings = get_settings()
    return PaymentService(FirestorePaymentRepository(settings), settings)


async def get_payment_service() -> PaymentService:
    return _payment_service()


def _line_principal(id_token: SecretStr) -> LinePrincipal:
    identity = verify_line_id_token(id_token.get_secret_value())
    return LinePrincipal(
        user_id=str(identity["sub"]),
        channel_id=str(identity.get("aud") or get_settings().line_customer_login_channel_id),
    )


def _admin_principal(actor: dict[str, object]) -> AdminPrincipal:
    raw_branches = actor.get("branchIds")
    branch_ids = (
        tuple(str(branch_id) for branch_id in raw_branches if branch_id)
        if isinstance(raw_branches, list)
        else (get_settings().default_branch_id,)
    )
    return AdminPrincipal(
        uid=str(actor["uid"]),
        email=str(actor.get("email", "")),
        role=AppRole(str(actor["role"])),
        branch_ids=branch_ids,
    )


def _idempotency_key(value: Annotated[str, Header(alias="Idempotency-Key")]) -> str:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValidationDomainError("Idempotency-Key must be a UUID v4") from error
    if parsed.version != 4:
        raise ValidationDomainError("Idempotency-Key must be a UUID v4")
    return str(parsed)


class LinePaymentRequest(StrictModel):
    line_id_token: SecretStr = Field(min_length=1, max_length=8192)
    device_type: BeamDeviceType = BeamDeviceType.WEB


class CreateAttemptRequest(LinePaymentRequest):
    tip_amount_satang: int = Field(ge=0)
    payment_method: BeamPaymentMethod = BeamPaymentMethod.QR_PROMPT_PAY


class PaymentOptionsResponse(StrictModel):
    booking_id: str
    payment_id: str
    status: PaymentStatus
    source: PaymentSource | None
    service_amount_satang: int
    currency: str
    eligible: bool
    reason: str | None
    tip_presets_satang: tuple[int, ...]
    custom_tip_max_satang: int | None
    methods: tuple[str, ...]
    version: int


class PaymentAttemptResponse(StrictModel):
    attempt_id: str
    payment_id: str
    status: str
    payment_method: BeamPaymentMethod
    action_required: str
    expires_at: datetime | None
    status_token: str
    image_base64: str | None
    redirect_url: str | None


class PaymentStatusRequest(StrictModel):
    status_token: SecretStr = Field(min_length=32, max_length=256)


class PaymentStatusResponse(StrictModel):
    payment_id: str
    booking_id: str
    status: PaymentStatus
    source: PaymentSource | None
    service_amount_satang: int
    tip_amount_satang: int
    gross_amount_satang: int
    paid_at: datetime | None


class RecordCashRequest(StrictModel):
    tip_amount_satang: int = Field(ge=0)
    expected_version: int = Field(ge=1)
    confirmed: bool


def _payment_status(value: PaymentStatusResult) -> PaymentStatusResponse:
    return PaymentStatusResponse.model_validate(value, from_attributes=True)


@public_router.post(
    "/bookings/{booking_id}/payment-options",
    response_model=PaymentOptionsResponse,
)
async def payment_options(
    booking_id: str,
    request: LinePaymentRequest,
    response: Response,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentOptionsResponse:
    principal = _line_principal(request.line_id_token)
    result = await payments.options(booking_id, principal, request.device_type)
    response.headers["Cache-Control"] = "no-store, private"
    return PaymentOptionsResponse(
        booking_id=result.booking_id,
        payment_id=result.payment_id,
        status=result.status,
        source=result.source,
        service_amount_satang=result.service_amount_satang,
        currency=result.currency,
        eligible=result.eligible,
        reason=result.reason,
        tip_presets_satang=result.tip_presets_satang,
        custom_tip_max_satang=result.custom_tip_max_satang,
        methods=tuple(method.value for method in result.enabled_methods),
        version=result.version,
    )


@admin_router.post(
    "/bookings/{booking_id}/payment-options",
    response_model=PaymentOptionsResponse,
)
async def admin_payment_options(
    booking_id: str,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    payments: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentOptionsResponse:
    result = await payments.admin_options(booking_id, _admin_principal(actor))
    response.headers["Cache-Control"] = "no-store, private"
    return PaymentOptionsResponse(
        booking_id=result.booking_id,
        payment_id=result.payment_id,
        status=result.status,
        source=result.source,
        service_amount_satang=result.service_amount_satang,
        currency=result.currency,
        eligible=result.eligible,
        reason=result.reason,
        tip_presets_satang=result.tip_presets_satang,
        custom_tip_max_satang=result.custom_tip_max_satang,
        methods=tuple(method.value for method in result.enabled_methods),
        version=result.version,
    )


@public_router.post(
    "/bookings/{booking_id}/payment-attempts",
    response_model=PaymentAttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_attempt(
    booking_id: str,
    request: CreateAttemptRequest,
    response: Response,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    payments: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentAttemptResponse:
    principal = _line_principal(request.line_id_token)
    result = await payments.create_attempt(
        booking_public_id=booking_id,
        principal=principal,
        tip_amount_satang=request.tip_amount_satang,
        payment_method=request.payment_method,
        device_type=request.device_type,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store, private"
    return PaymentAttemptResponse.model_validate(result, from_attributes=True)


@public_router.post(
    "/payment-status:resolve",
    response_model=PaymentStatusResponse,
)
async def resolve_payment_status(
    request: PaymentStatusRequest,
    response: Response,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentStatusResponse:
    result = await payments.resolve_status(request.status_token.get_secret_value())
    response.headers["Cache-Control"] = "no-store, private"
    return _payment_status(result)


@admin_router.post(
    "/bookings/{booking_id}/payments:record-cash",
    response_model=PaymentStatusResponse,
)
async def record_cash_payment(
    booking_id: str,
    request: RecordCashRequest,
    response: Response,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    payments: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentStatusResponse:
    if not request.confirmed:
        raise ValidationDomainError("Cash receipt confirmation is required")
    result = await payments.record_cash(
        booking_public_id=booking_id,
        principal=_admin_principal(actor),
        tip_amount_satang=request.tip_amount_satang,
        expected_version=request.expected_version,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store, private"
    return _payment_status(result)


@webhook_router.post("/beam", status_code=status.HTTP_202_ACCEPTED)
async def beam_webhook(
    request: Request,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    x_beam_signature: Annotated[str | None, Header(alias="X-Beam-Signature")] = None,
    x_beam_event: Annotated[str | None, Header(alias="X-Beam-Event")] = None,
) -> dict[str, bool]:
    raw_body = await request.body()
    if len(raw_body) > 128 * 1024:
        raise AuthenticationInvalid("Beam webhook payload is invalid")
    settings = get_settings()
    webhook_key = settings.beam_webhook_hmac_key
    if (
        webhook_key is None
        or x_beam_signature is None
        or not verify_beam_webhook_signature(
            raw_body,
            x_beam_signature,
            webhook_key.get_secret_value(),
        )
    ):
        raise AuthenticationInvalid("Beam webhook signature is invalid")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise ValidationDomainError("Beam webhook body is invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValidationDomainError("Beam webhook body must be an object")
    charge_id = payload.get("chargeId")
    if not isinstance(charge_id, str) or not charge_id or len(charge_id) > 200:
        raise ValidationDomainError("Beam webhook chargeId is invalid")
    processed = await payments.process_webhook(
        event_type=x_beam_event or "",
        charge_id=charge_id,
        raw_body=raw_body,
    )
    return {"accepted": processed}
