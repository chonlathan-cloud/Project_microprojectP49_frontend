import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from app.core.errors import (
    FinancialConflict,
    PaymentDeviceUnsupported,
    PaymentMethodUnavailable,
    PaymentNotEligible,
    PersistenceUnavailable,
)
from app.core.settings import Settings
from app.core.types import BeamDeviceType, BeamPaymentMethod, PaymentSource, PaymentStatus
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

logger = logging.getLogger(__name__)


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
    enabled_methods: tuple[BeamPaymentMethod, ...]
    version: int
    reconciliation: "PaymentReconciliationTarget | None" = None


@dataclass(frozen=True, slots=True)
class PaymentReconciliationTarget:
    attempt_id: str
    payment_id: str
    provider_reference_id: str
    provider_charge_id: str | None
    expires_at: datetime


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
    payment_method: BeamPaymentMethod
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
        payment_method: BeamPaymentMethod,
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

    async def ensure_beam_charge_link(self, charge: BeamCharge, now: datetime) -> bool: ...

    async def mark_reconciliation_missing(
        self,
        target: PaymentReconciliationTarget,
        *,
        not_before: datetime,
        now: datetime,
    ) -> None: ...

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

    async def _reconcile_options(
        self,
        options: PaymentOptions,
        *,
        reload_options: Callable[[], Awaitable[PaymentOptions]],
    ) -> PaymentOptions:
        target = options.reconciliation
        if target is None or self._settings.beam_readiness_errors():
            return options
        now = datetime.now(UTC)
        try:
            async with BeamClient(self._settings) as client:
                if target.provider_charge_id:
                    try:
                        charge = await client.get_charge(target.provider_charge_id)
                        charge_list = None
                    except BeamRejectedError:
                        charge = None
                        charge_list = await client.list_charges_by_reference(
                            target.provider_reference_id
                        )
                else:
                    charge = None
                    charge_list = await client.list_charges_by_reference(
                        target.provider_reference_id
                    )
        except (BeamRetryableError, BeamRejectedError, BeamConfigurationError):
            return options

        if charge is None:
            if charge_list is None or charge_list.total_count > 1:
                return options
            charge = charge_list.charges[0] if charge_list.charges else None
        if charge is None:
            not_before = target.expires_at + timedelta(minutes=5)
            if now < not_before:
                return options
            await self._repository.mark_reconciliation_missing(
                target,
                not_before=not_before,
                now=now,
            )
            return await reload_options()

        linked = await self._repository.ensure_beam_charge_link(charge, now)
        if not linked:
            return options
        event_id = sha256(
            f"beam-reconcile:{charge.charge_id}:{charge.status}".encode()
        ).hexdigest()
        event_type = (
            "charge.succeeded"
            if charge.status == "SUCCEEDED"
            else "charge.failed"
            if charge.status in {"FAILED", "EXPIRED", "CANCELED", "CANCELLED"}
            else "charge.reconcile"
        )
        accepted = await self._repository.accept_webhook(
            event_id,
            event_type,
            charge.charge_id,
            now,
        )
        if accepted:
            await self._repository.settle_beam_charge(event_id, charge, now)
        return await reload_options()

    async def options(
        self,
        booking_public_id: str,
        principal: LinePrincipal,
        device_type: BeamDeviceType = BeamDeviceType.WEB,
    ) -> PaymentOptions:
        options = await self._repository.get_options(
            booking_public_id, principal, datetime.now(UTC)
        )
        options = await self._reconcile_options(
            options,
            reload_options=lambda: self._repository.get_options(
                booking_public_id, principal, datetime.now(UTC)
            ),
        )
        methods = options.enabled_methods
        if device_type is BeamDeviceType.WEB:
            methods = tuple(
                method
                for method in methods
                if method is BeamPaymentMethod.QR_PROMPT_PAY
            )
        if methods == options.enabled_methods:
            return options
        return replace(options, enabled_methods=methods)

    async def admin_options(
        self, booking_public_id: str, principal: AdminPrincipal
    ) -> PaymentOptions:
        require_admin_financial_action(
            role=principal.role,
            action=AdminFinancialAction.RECORD_CASH,
        )
        options = await self._repository.get_admin_options(
            booking_public_id, principal, datetime.now(UTC)
        )
        return await self._reconcile_options(
            options,
            reload_options=lambda: self._repository.get_admin_options(
                booking_public_id, principal, datetime.now(UTC)
            ),
        )

    async def create_attempt(
        self,
        *,
        booking_public_id: str,
        principal: LinePrincipal,
        tip_amount_satang: int,
        payment_method: BeamPaymentMethod,
        device_type: BeamDeviceType,
        idempotency_key: str,
    ) -> PaymentAttemptResult:
        validate_tip_amount(
            tip_amount_satang,
            custom_max_satang=self._settings.tip_custom_max_satang,
        )
        if self._settings.beam_readiness_errors():
            raise PersistenceUnavailable("Beam payment is unavailable")
        options = await self.options(booking_public_id, principal, device_type)
        if not options.eligible:
            raise PaymentNotEligible(options.reason or "Payment is unavailable")
        if payment_method not in options.enabled_methods:
            raise PaymentMethodUnavailable("Selected Beam payment method is not enabled")
        if (
            payment_method is not BeamPaymentMethod.QR_PROMPT_PAY
            and device_type is BeamDeviceType.WEB
        ):
            raise PaymentDeviceUnsupported(
                "Mobile banking requires an iOS or Android device"
            )
        request_digest = sha256(
            f"{booking_public_id}:{principal.channel_id}:{principal.user_id}:"
            f"{tip_amount_satang}:{payment_method.value}:{device_type.value}".encode()
        ).hexdigest()
        prepared = await self._repository.begin_attempt(
            booking_public_id=booking_public_id,
            principal=principal,
            tip_amount_satang=tip_amount_satang,
            payment_method=payment_method,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            now=datetime.now(UTC),
        )
        raw = None
        try:
            async with BeamClient(self._settings) as client:
                if payment_method is BeamPaymentMethod.QR_PROMPT_PAY:
                    raw = await client.create_qr_promptpay_charge(
                        amount_satang=prepared.total_amount_satang,
                        reference_id=prepared.provider_reference_id,
                        expires_at=prepared.requested_expires_at,
                        idempotency_key=prepared.provider_idempotency_key,
                    )
                else:
                    raw = await client.create_mobile_banking_charge(
                        amount_satang=prepared.total_amount_satang,
                        reference_id=prepared.provider_reference_id,
                        payment_method=payment_method,
                        device_type=device_type,
                        idempotency_key=prepared.provider_idempotency_key,
                    )
            action = normalize_charge_action(
                raw,
                requested_method=payment_method,
                requested_expires_at=prepared.requested_expires_at,
                allowed_redirect_hosts=(
                    self._settings.configured_beam_redirect_allowed_hosts
                ),
            )
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
        except BeamConfigurationError as error:
            await self._repository.mark_create_unknown(prepared.attempt_id, datetime.now(UTC))
            logger.exception(
                "Beam charge response validation failed: %s",
                error,
                extra={
                    "attemptId": prepared.attempt_id,
                    "paymentMethod": payment_method.value,
                    "providerChargeId": (
                        raw.get("chargeId") if isinstance(raw, dict) else None
                    ),
                    "providerActionRequired": (
                        raw.get("actionRequired") if isinstance(raw, dict) else None
                    ),
                    "providerPaymentMethodType": (
                        raw.get("paymentMethodType") if isinstance(raw, dict) else None
                    ),
                },
            )
            raise PersistenceUnavailable("Beam payment response is invalid") from None

        effective_expires_at = action.expires_at or prepared.requested_expires_at
        await self._repository.activate_attempt(
            prepared,
            provider_charge_id=action.charge_id,
            action_required=action.action_required,
            provider_expires_at=effective_expires_at,
            now=datetime.now(UTC),
        )
        return PaymentAttemptResult(
            attempt_id=prepared.attempt_id,
            payment_id=prepared.payment_id,
            status="ACTIVE",
            payment_method=payment_method,
            action_required=action.action_required,
            expires_at=effective_expires_at,
            status_token=prepared.status_token,
            image_base64=action.image_base64,
            redirect_url=action.redirect_url,
        )

    async def process_webhook(self, *, event_type: str, charge_id: str, raw_body: bytes) -> bool:
        if event_type not in {"charge.succeeded", "charge.failed"}:
            return False
        try:
            async with BeamClient(self._settings) as client:
                charge = await client.get_charge(charge_id)
        except (BeamRetryableError, BeamAmbiguousCreateError):
            raise PersistenceUnavailable(
                "Beam webhook reconciliation is temporarily unavailable"
            ) from None
        except (BeamConfigurationError, BeamRejectedError):
            raise PersistenceUnavailable("Beam webhook reconciliation is unavailable") from None
        now = datetime.now(UTC)
        if not await self._repository.ensure_beam_charge_link(charge, now):
            return False
        event_id = sha256(event_type.encode() + b":" + raw_body).hexdigest()
        accepted = await self._repository.accept_webhook(
            event_id, event_type, charge_id, now
        )
        if not accepted:
            return True
        await self._repository.settle_beam_charge(event_id, charge, now)
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
