from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.application import payments as payment_application
from app.application.payments import (
    PaymentOptions,
    PaymentReconciliationTarget,
    PaymentService,
    PreparedAttempt,
)
from app.core.settings import Settings
from app.core.types import BeamDeviceType, BeamPaymentMethod, PaymentStatus
from app.domains.identity.models import LinePrincipal
from app.integrations.beam import BeamCharge, BeamChargeList


def settings() -> Settings:
    return Settings(
        beam_enabled=True,
        beam_merchant_id="merchant-test",
        beam_api_key=SecretStr("api-key-test"),
        beam_webhook_hmac_key=SecretStr("a2V5"),
        beam_return_url="https://customer.invalid/payment/result",
    )


def options(
    *,
    eligible: bool,
    reason: str | None,
    reconciliation: PaymentReconciliationTarget | None = None,
) -> PaymentOptions:
    return PaymentOptions(
        booking_id="BK-001",
        payment_id="pay_001",
        status=PaymentStatus.DUE,
        source=None,
        service_amount_satang=60_000,
        currency="THB",
        eligible=eligible,
        reason=reason,
        tip_presets_satang=(0, 2_000, 5_000, 10_000),
        custom_tip_max_satang=50_000,
        enabled_methods=(BeamPaymentMethod.QR_PROMPT_PAY,),
        version=1,
        reconciliation=reconciliation,
    )


class Repository:
    def __init__(self, before: PaymentOptions, after: PaymentOptions) -> None:
        self.before = before
        self.after = after
        self.reconciled = False
        self.linked: list[BeamCharge] = []
        self.accepted: list[tuple[str, str, str]] = []
        self.settled: list[BeamCharge] = []
        self.missing: list[PaymentReconciliationTarget] = []

    async def get_options(self, *_args) -> PaymentOptions:
        return self.after if self.reconciled else self.before

    async def ensure_beam_charge_link(self, charge: BeamCharge, _now: datetime) -> bool:
        self.linked.append(charge)
        return True

    async def accept_webhook(
        self,
        event_id: str,
        event_type: str,
        charge_id: str,
        _now: datetime,
    ) -> bool:
        self.accepted.append((event_id, event_type, charge_id))
        return True

    async def settle_beam_charge(
        self,
        _event_id: str,
        charge: BeamCharge,
        _now: datetime,
    ) -> None:
        self.settled.append(charge)
        self.reconciled = charge.status in {
            "SUCCEEDED",
            "FAILED",
            "EXPIRED",
            "CANCELED",
            "CANCELLED",
        }

    async def mark_reconciliation_missing(
        self,
        target: PaymentReconciliationTarget,
        *,
        not_before: datetime,
        now: datetime,
    ) -> None:
        assert now >= not_before
        self.missing.append(target)
        self.reconciled = True


class FakeBeamClient:
    charge: BeamCharge | None = None
    charge_list = BeamChargeList((), 0)

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        pass

    async def get_charge(self, _charge_id: str) -> BeamCharge:
        assert self.charge is not None
        return self.charge

    async def list_charges_by_reference(self, _reference_id: str) -> BeamChargeList:
        return self.charge_list


class AttemptRepository(Repository):
    def __init__(self, payment_options: PaymentOptions) -> None:
        super().__init__(payment_options, payment_options)
        self.activated: list[dict[str, object]] = []

    async def begin_attempt(self, **_kwargs) -> PreparedAttempt:
        return PreparedAttempt(
            attempt_id="pat_playground_001",
            payment_id="pay_001",
            provider_reference_id="SPA-PAY-pay_001-pat_playground_001",
            provider_idempotency_key="provider-idempotency-key",
            total_amount_satang=60_000,
            requested_expires_at=datetime(2026, 9, 1, 6, 18, tzinfo=UTC),
            status_token="opaque-payment-status-token-with-minimum-length",
        )

    async def activate_attempt(self, _prepared, **kwargs) -> None:
        self.activated.append(kwargs)


class FakePlaygroundCreateClient(FakeBeamClient):
    async def create_mobile_banking_charge(self, **_kwargs) -> dict[str, object]:
        return {
            "chargeId": "ch_playground_001",
            "paymentMethodType": "KPLUS",
            "actionRequired": "ENCODED_IMAGE",
            "encodedImage": {
                "expiry": None,
                "imageBase64Encoded": "iVBORw0KGgo=",
            },
        }


@pytest.mark.asyncio
async def test_options_reconciles_failed_charge_by_reference(monkeypatch) -> None:
    target = PaymentReconciliationTarget(
        attempt_id="pat_001",
        payment_id="pay_001",
        provider_reference_id="SPA-PAY-pay_001-pat_001",
        provider_charge_id=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    charge = BeamCharge(
        charge_id="ch_001",
        merchant_id="merchant-test",
        reference_id=target.provider_reference_id,
        status="FAILED",
        currency="THB",
        amount=60_000,
        transaction_time=None,
        failure_code="CH_PROCESSING_FAILED",
    )
    FakeBeamClient.charge_list = BeamChargeList((charge,), 1)
    monkeypatch.setattr(payment_application, "BeamClient", FakeBeamClient)
    repository = Repository(
        options(
            eligible=False,
            reason="PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED",
            reconciliation=target,
        ),
        options(eligible=False, reason="OUTSIDE_SERVICE_DATE"),
    )

    result = await PaymentService(repository, settings()).options(
        "BK-001",
        LinePrincipal(user_id="U-001", channel_id="line-channel"),
    )

    assert result.reason == "OUTSIDE_SERVICE_DATE"
    assert repository.linked == [charge]
    assert repository.accepted[0][1:] == ("charge.failed", "ch_001")
    assert repository.settled == [charge]


@pytest.mark.asyncio
async def test_options_reconciles_succeeded_charge_by_reference(monkeypatch) -> None:
    target = PaymentReconciliationTarget(
        attempt_id="pat_001",
        payment_id="pay_001",
        provider_reference_id="SPA-PAY-pay_001-pat_001",
        provider_charge_id=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    charge = BeamCharge(
        charge_id="ch_001",
        merchant_id="merchant-test",
        reference_id=target.provider_reference_id,
        status="SUCCEEDED",
        currency="THB",
        amount=60_000,
        transaction_time=datetime.now(UTC),
    )
    FakeBeamClient.charge_list = BeamChargeList((charge,), 1)
    monkeypatch.setattr(payment_application, "BeamClient", FakeBeamClient)
    repository = Repository(
        options(
            eligible=False,
            reason="PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED",
            reconciliation=target,
        ),
        options(eligible=False, reason="NOTHING_DUE"),
    )

    result = await PaymentService(repository, settings()).options(
        "BK-001",
        LinePrincipal(user_id="U-001", channel_id="line-channel"),
    )

    assert result.reason == "NOTHING_DUE"
    assert repository.accepted[0][1:] == ("charge.succeeded", "ch_001")
    assert repository.settled == [charge]


@pytest.mark.asyncio
async def test_options_links_pending_charge_and_keeps_attempt_blocked(monkeypatch) -> None:
    target = PaymentReconciliationTarget(
        attempt_id="pat_001",
        payment_id="pay_001",
        provider_reference_id="SPA-PAY-pay_001-pat_001",
        provider_charge_id=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    charge = BeamCharge(
        charge_id="ch_001",
        merchant_id="merchant-test",
        reference_id=target.provider_reference_id,
        status="PENDING",
        currency="THB",
        amount=60_000,
        transaction_time=None,
    )
    FakeBeamClient.charge_list = BeamChargeList((charge,), 1)
    monkeypatch.setattr(payment_application, "BeamClient", FakeBeamClient)
    pending = options(
        eligible=False,
        reason="PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED",
        reconciliation=target,
    )
    repository = Repository(pending, options(eligible=True, reason=None))

    result = await PaymentService(repository, settings()).options(
        "BK-001",
        LinePrincipal(user_id="U-001", channel_id="line-channel"),
    )

    assert result is pending
    assert repository.accepted[0][1:] == ("charge.reconcile", "ch_001")
    assert repository.settled == [charge]


@pytest.mark.asyncio
async def test_options_releases_expired_unknown_when_beam_has_no_charge(monkeypatch) -> None:
    target = PaymentReconciliationTarget(
        attempt_id="pat_001",
        payment_id="pay_001",
        provider_reference_id="SPA-PAY-pay_001-pat_001",
        provider_charge_id=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    FakeBeamClient.charge_list = BeamChargeList((), 0)
    monkeypatch.setattr(payment_application, "BeamClient", FakeBeamClient)
    repository = Repository(
        options(
            eligible=False,
            reason="PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED",
            reconciliation=target,
        ),
        options(eligible=True, reason=None),
    )

    result = await PaymentService(repository, settings()).options(
        "BK-001",
        LinePrincipal(user_id="U-001", channel_id="line-channel"),
    )

    assert result.eligible is True
    assert repository.missing == [target]
    assert repository.linked == []


@pytest.mark.asyncio
async def test_options_keeps_unknown_attempt_during_recovery_grace(monkeypatch) -> None:
    target = PaymentReconciliationTarget(
        attempt_id="pat_001",
        payment_id="pay_001",
        provider_reference_id="SPA-PAY-pay_001-pat_001",
        provider_charge_id=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    FakeBeamClient.charge_list = BeamChargeList((), 0)
    monkeypatch.setattr(payment_application, "BeamClient", FakeBeamClient)
    pending = options(
        eligible=False,
        reason="PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED",
        reconciliation=target,
    )
    repository = Repository(pending, options(eligible=True, reason=None))

    result = await PaymentService(repository, settings()).options(
        "BK-001",
        LinePrincipal(user_id="U-001", channel_id="line-channel"),
    )

    assert result is pending
    assert repository.missing == []


@pytest.mark.asyncio
async def test_webhook_ignores_charge_that_cannot_be_linked(monkeypatch) -> None:
    charge = BeamCharge(
        charge_id="ch_unknown",
        merchant_id="merchant-test",
        reference_id="another-system",
        status="FAILED",
        currency="THB",
        amount=60_000,
        transaction_time=None,
    )
    FakeBeamClient.charge = charge
    monkeypatch.setattr(payment_application, "BeamClient", FakeBeamClient)
    repository = Repository(
        options(eligible=False, reason="PAYMENT_REVIEW_REQUIRED"),
        options(eligible=False, reason="PAYMENT_REVIEW_REQUIRED"),
    )

    async def not_linked(_charge: BeamCharge, _now: datetime) -> bool:
        return False

    repository.ensure_beam_charge_link = not_linked  # type: ignore[method-assign]

    processed = await PaymentService(repository, settings()).process_webhook(
        event_type="charge.failed",
        charge_id=charge.charge_id,
        raw_body=b'{"chargeId":"ch_unknown"}',
    )

    assert processed is False
    assert repository.accepted == []


@pytest.mark.asyncio
async def test_payment_options_expose_mobile_methods_only_to_mobile_devices() -> None:
    all_methods = tuple(BeamPaymentMethod)
    configured = replace(
        options(eligible=True, reason=None),
        enabled_methods=all_methods,
    )
    principal = LinePrincipal(user_id="U-001", channel_id="line-channel")

    web_result = await PaymentService(
        Repository(configured, configured),
        settings(),
    ).options("BK-001", principal, BeamDeviceType.WEB)
    ios_result = await PaymentService(
        Repository(configured, configured),
        settings(),
    ).options("BK-001", principal, BeamDeviceType.IOS)

    assert web_result.enabled_methods == (BeamPaymentMethod.QR_PROMPT_PAY,)
    assert ios_result.enabled_methods == all_methods


@pytest.mark.asyncio
async def test_create_attempt_activates_playground_mobile_encoded_image(monkeypatch) -> None:
    mobile_options = replace(
        options(eligible=True, reason=None),
        enabled_methods=(BeamPaymentMethod.KPLUS, BeamPaymentMethod.QR_PROMPT_PAY),
    )
    repository = AttemptRepository(mobile_options)
    monkeypatch.setattr(payment_application, "BeamClient", FakePlaygroundCreateClient)

    result = await PaymentService(
        repository,
        settings().model_copy(
            update={"beam_payment_methods": "KPLUS,QR_PROMPT_PAY"}
        ),
    ).create_attempt(
        booking_public_id="BK-001",
        principal=LinePrincipal(user_id="U-001", channel_id="line-channel"),
        tip_amount_satang=0,
        payment_method=BeamPaymentMethod.KPLUS,
        device_type=BeamDeviceType.IOS,
        idempotency_key="2d4e72d3-4ab8-4f99-a09a-c81fa1caa49c",
    )

    assert result.action_required == "ENCODED_IMAGE"
    assert result.image_base64 == "iVBORw0KGgo="
    assert result.redirect_url is None
    assert repository.activated[0]["provider_charge_id"] == "ch_playground_001"
    assert repository.activated[0]["action_required"] == "ENCODED_IMAGE"
