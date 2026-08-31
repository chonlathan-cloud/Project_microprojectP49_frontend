from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from app.core.errors import FinancialConflict, PersistenceUnavailable
from app.core.settings import Settings
from app.core.types import PaymentSource, PaymentStatus
from app.domains.identity.models import AdminPrincipal, LinePrincipal
from app.domains.payments.policy import (
    TIP_PRESETS_SATANG,
    AdminFinancialAction,
    require_admin_financial_action,
    validate_tip_amount,
)
from app.integrations.beam import (
    BeamAmbiguousCreateError,
    BeamCharge,
    BeamClient,
    BeamConfigurationError,
    BeamRejectedError,
    BeamRetryableError,
    normalize_charge_action,
)


@dataclass(frozen=True, slots=True)
class PaymentOptions:
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
    beam_qr_enabled: bool
    version: int


@dataclass(frozen=True, slots=True)
class PreparedAttempt:
    attempt_id: str
    payment_id: str
    provider_reference_id: str
    provider_idempotency_key: str
    total_amount_satang: int
    requested_expires_at: datetime
    status_token: str


@dataclass(frozen=True, slots=True)
class PaymentAttemptResult:
    attempt_id: str
    payment_id: str
    status: str
    action_required: str
    expires_at: datetime | None
    status_token: str
    image_base64: str | None = None
    redirect_url: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentStatusResult:
    payment_id: str
    booking_id: str
    status: PaymentStatus
    source: PaymentSource | None
    service_amount_satang: int
    tip_amount_satang: int
    gross_amount_satang: int
    paid_at: datetime | None


class PaymentRepository(Protocol):
    async def get_options(
        self, booking_public_id: str, principal: LinePrincipal, now: datetime
    ) -> PaymentOptions: ...

    async def get_admin_options(
        self, booking_public_id: str, principal: AdminPrincipal, now: datetime
    ) -> PaymentOptions: ...

    async def begin_attempt(
        self,
        *,
        booking_public_id: str,
        principal: LinePrincipal,
        tip_amount_satang: int,
        idempotency_key: str,
        request_digest: str,
        now: datetime,
    ) -> PreparedAttempt: ...

    async def activate_attempt(
        self,
        prepared: PreparedAttempt,
        *,
        provider_charge_id: str,
        action_required: str,
        provider_expires_at: datetime | None,
        now: datetime,
    ) -> None: ...

    async def mark_create_unknown(self, attempt_id: str, now: datetime) -> None: ...

    async def mark_create_failed(self, attempt_id: str, now: datetime) -> None: ...

    async def accept_webhook(
        self, event_id: str, event_type: str, charge_id: str, now: datetime
    ) -> bool: ...

    async def settle_beam_charge(
        self, event_id: str, charge: BeamCharge, now: datetime
    ) -> None: ...

    async def resolve_status(self, status_token: str) -> PaymentStatusResult: ...

    async def record_cash(
        self,
        *,
        booking_public_id: str,
        principal: AdminPrincipal,
        tip_amount_satang: int,
        expected_version: int,
        idempotency_key: str,
        now: datetime,
    ) -> PaymentStatusResult: ...


class PaymentService:
    def __init__(self, repository: PaymentRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def options(self, booking_public_id: str, principal: LinePrincipal) -> PaymentOptions:
        return await self._repository.get_options(booking_public_id, principal, datetime.now(UTC))

    async def admin_options(
        self, booking_public_id: str, principal: AdminPrincipal
    ) -> PaymentOptions:
        require_admin_financial_action(
            role=principal.role,
            action=AdminFinancialAction.RECORD_CASH,
        )
        return await self._repository.get_admin_options(
            booking_public_id, principal, datetime.now(UTC)
        )

    async def create_attempt(
        self,
        *,
        booking_public_id: str,
        principal: LinePrincipal,
        tip_amount_satang: int,
        idempotency_key: str,
    ) -> PaymentAttemptResult:
        validate_tip_amount(
            tip_amount_satang,
            custom_max_satang=self._settings.tip_custom_max_satang,
        )
        if self._settings.beam_readiness_errors():
            raise PersistenceUnavailable("Beam payment is unavailable")
        request_digest = sha256(
            f"{booking_public_id}:{principal.channel_id}:{principal.user_id}:"
            f"{tip_amount_satang}:QR_PROMPT_PAY".encode()
        ).hexdigest()
        prepared = await self._repository.begin_attempt(
            booking_public_id=booking_public_id,
            principal=principal,
            tip_amount_satang=tip_amount_satang,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            now=datetime.now(UTC),
        )
        try:
            async with BeamClient(self._settings) as client:
                raw = await client.create_qr_promptpay_charge(
                    amount_satang=prepared.total_amount_satang,
                    reference_id=prepared.provider_reference_id,
                    expires_at=prepared.requested_expires_at,
                    idempotency_key=prepared.provider_idempotency_key,
                )
            action = normalize_charge_action(raw)
        except BeamRejectedError:
            await self._repository.mark_create_failed(prepared.attempt_id, datetime.now(UTC))
            raise PersistenceUnavailable("Beam rejected the payment request") from None
        except BeamAmbiguousCreateError:
            await self._repository.mark_create_unknown(prepared.attempt_id, datetime.now(UTC))
            raise PersistenceUnavailable(
                "Beam charge outcome is unknown; retry status reconciliation"
            ) from None
        except BeamRetryableError:
            raise PersistenceUnavailable("Beam payment is temporarily unavailable") from None
        except BeamConfigurationError:
            await self._repository.mark_create_unknown(prepared.attempt_id, datetime.now(UTC))
            raise PersistenceUnavailable("Beam payment response is invalid") from None

        await self._repository.activate_attempt(
            prepared,
            provider_charge_id=action.charge_id,
            action_required=action.action_required,
            provider_expires_at=action.expires_at,
            now=datetime.now(UTC),
        )
        return PaymentAttemptResult(
            attempt_id=prepared.attempt_id,
            payment_id=prepared.payment_id,
            status="ACTIVE",
            action_required=action.action_required,
            expires_at=action.expires_at,
            status_token=prepared.status_token,
            image_base64=action.image_base64,
            redirect_url=action.redirect_url,
        )

    async def process_webhook(self, *, event_type: str, charge_id: str, raw_body: bytes) -> bool:
        if event_type not in {"charge.succeeded", "charge.failed"}:
            return False
        event_id = sha256(event_type.encode() + b":" + raw_body).hexdigest()
        accepted = await self._repository.accept_webhook(
            event_id, event_type, charge_id, datetime.now(UTC)
        )
        if not accepted:
            return True
        try:
            async with BeamClient(self._settings) as client:
                charge = await client.get_charge(charge_id)
        except (BeamRetryableError, BeamAmbiguousCreateError):
            raise PersistenceUnavailable(
                "Beam webhook reconciliation is temporarily unavailable"
            ) from None
        except (BeamConfigurationError, BeamRejectedError):
            raise PersistenceUnavailable("Beam webhook reconciliation is unavailable") from None
        await self._repository.settle_beam_charge(event_id, charge, datetime.now(UTC))
        return True

    async def resolve_status(self, status_token: str) -> PaymentStatusResult:
        return await self._repository.resolve_status(status_token)

    async def record_cash(
        self,
        *,
        booking_public_id: str,
        principal: AdminPrincipal,
        tip_amount_satang: int,
        expected_version: int,
        idempotency_key: str,
    ) -> PaymentStatusResult:
        require_admin_financial_action(
            role=principal.role,
            action=AdminFinancialAction.RECORD_CASH,
        )
        validate_tip_amount(
            tip_amount_satang,
            custom_max_satang=self._settings.tip_custom_max_satang,
        )
        if expected_version < 1:
            raise FinancialConflict("Payment version must be positive")
        return await self._repository.record_cash(
            booking_public_id=booking_public_id,
            principal=principal,
            tip_amount_satang=tip_amount_satang,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            now=datetime.now(UTC),
        )


def customer_tip_presets(settings: Settings) -> tuple[int, ...]:
    del settings
    return TIP_PRESETS_SATANG
