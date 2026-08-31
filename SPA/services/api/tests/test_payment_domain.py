from datetime import UTC, date, datetime, timedelta

import pytest

from app.application.financial_ledger import (
    AuthoritativePaymentCommand,
    InMemoryFinancialLedger,
)
from app.core.errors import FinancialConflict, FinancialInvariantError
from app.core.types import (
    AppRole,
    BookingStatus,
    CashSettlementStatus,
    PaymentSource,
    PaymentStatus,
)
from app.domains.payments.eligibility import (
    attempt_expires_at,
    evaluate_payment_eligibility,
)
from app.domains.payments.models import MoneyBreakdown, Payment, ServiceLineSnapshot
from app.domains.payments.policy import (
    AdminFinancialAction,
    require_admin_financial_action,
    validate_tip_amount,
)


def payment() -> Payment:
    return Payment(
        payment_id="pay_001",
        booking_doc_id="booking-doc-001",
        booking_public_id="BK-20260831-001",
        branch_id="branch_001",
        amounts=MoneyBreakdown(
            service_amount_satang=35_000,
            tip_amount_satang=5_000,
            gross_amount_satang=40_000,
        ),
        service_lines=(
            ServiceLineSnapshot(
                sku="FOOT-60",
                name="นวดเท้า 60 นาที",
                quantity=1,
                unit_price_satang=35_000,
            ),
        ),
    )


def test_money_requires_exact_integer_satang_total() -> None:
    with pytest.raises(FinancialInvariantError, match="integer satang"):
        MoneyBreakdown(35_000, 5_000.0, 40_000)  # type: ignore[arg-type]
    with pytest.raises(FinancialInvariantError, match="must equal"):
        MoneyBreakdown(35_000, 5_000, 40_001)


def test_payment_is_eligible_only_after_completion_on_service_date() -> None:
    now = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    result = evaluate_payment_eligibility(
        booking_status=BookingStatus.COMPLETED,
        booking_local_date=date(2026, 8, 31),
        payment_status=PaymentStatus.DUE,
        amount_due_satang=35_000,
        has_unexpired_attempt=False,
        on_correction_hold=False,
        now=now,
    )
    assert result.eligible

    result = evaluate_payment_eligibility(
        booking_status=BookingStatus.IN_SERVICE,
        booking_local_date=date(2026, 8, 31),
        payment_status=PaymentStatus.DUE,
        amount_due_satang=35_000,
        has_unexpired_attempt=False,
        on_correction_hold=False,
        now=now,
    )
    assert not result.eligible
    assert result.reason == "BOOKING_NOT_COMPLETED"


def test_attempt_keeps_full_fifteen_minutes_across_midnight() -> None:
    created = datetime.fromisoformat("2026-08-31T23:50:00+07:00")
    assert attempt_expires_at(created) == datetime.fromisoformat("2026-09-01T00:05:00+07:00")


def test_tip_presets_and_custom_maximum_are_enforced() -> None:
    for preset in (0, 2_000, 5_000, 10_000):
        validate_tip_amount(preset, custom_max_satang=None)
    with pytest.raises(FinancialInvariantError, match="disabled"):
        validate_tip_amount(3_000, custom_max_satang=None)
    validate_tip_amount(3_000, custom_max_satang=5_000)
    with pytest.raises(FinancialInvariantError, match="exceeds"):
        validate_tip_amount(5_001, custom_max_satang=5_000)


def test_refund_and_correction_are_admin_only_and_require_reason() -> None:
    with pytest.raises(FinancialInvariantError, match="ADMIN"):
        require_admin_financial_action(
            role=AppRole.STAFF,
            action=AdminFinancialAction.REFUND,
            reason="ลูกค้าขอคืนเงิน",
        )
    with pytest.raises(FinancialInvariantError, match="require a reason"):
        require_admin_financial_action(
            role=AppRole.ADMIN,
            action=AdminFinancialAction.CORRECTION,
            reason="  ",
        )
    assert (
        require_admin_financial_action(
            role=AppRole.ADMIN,
            action=AdminFinancialAction.REFUND,
            reason="  ลูกค้าขอคืนเงิน  ",
        )
        == "ลูกค้าขอคืนเงิน"
    )


def test_late_override_allows_new_attempt_after_service_date() -> None:
    now = datetime.fromisoformat("2026-09-01T10:00:00+07:00")
    result = evaluate_payment_eligibility(
        booking_status=BookingStatus.COMPLETED,
        booking_local_date=date(2026, 8, 31),
        payment_status=PaymentStatus.DUE,
        amount_due_satang=35_000,
        has_unexpired_attempt=False,
        on_correction_hold=False,
        now=now,
        late_override_until=now + timedelta(minutes=10),
    )
    assert result.eligible


def test_beam_success_atomically_creates_one_deterministic_export() -> None:
    ledger = InMemoryFinancialLedger()
    ledger.add_payment(payment())
    paid_at = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
    command = AuthoritativePaymentCommand(
        payment_id="pay_001",
        expected_version=1,
        source=PaymentSource.BEAM,
        paid_at=paid_at,
        provider_resource_id="beam_charge_001",
    )

    first = ledger.commit_authoritative_payment(command)
    replay = ledger.commit_authoritative_payment(command)

    assert first.payment.status is PaymentStatus.PAID
    assert first.payment.cash_settlement_status is CashSettlementStatus.NOT_APPLICABLE
    assert first.accounting_export.gross_amount_satang == 40_000
    assert first.accounting_export.accounting_date == date(2026, 8, 31)
    assert len(first.accounting_export.external_document_id) <= 36
    assert not first.replayed
    assert replay.replayed
    assert replay.accounting_export == first.accounting_export
    assert len(ledger.exports()) == 1


def test_cash_receipt_is_paid_but_remains_unsettled() -> None:
    ledger = InMemoryFinancialLedger()
    ledger.add_payment(payment())
    result = ledger.commit_authoritative_payment(
        AuthoritativePaymentCommand(
            payment_id="pay_001",
            expected_version=1,
            source=PaymentSource.CASH,
            paid_at=datetime(2026, 8, 31, 20, 0, tzinfo=UTC),
            cash_received_by="admin_001",
        )
    )
    assert result.payment.cash_settlement_status is CashSettlementStatus.UNSETTLED
    assert result.accounting_export.payment_strategy == "CASH"


def test_paid_payment_rejects_different_authoritative_evidence() -> None:
    ledger = InMemoryFinancialLedger()
    ledger.add_payment(payment())
    paid_at = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)
    ledger.commit_authoritative_payment(
        AuthoritativePaymentCommand(
            payment_id="pay_001",
            expected_version=1,
            source=PaymentSource.BEAM,
            paid_at=paid_at,
            provider_resource_id="beam_charge_001",
        )
    )
    with pytest.raises(FinancialConflict, match="different evidence"):
        ledger.commit_authoritative_payment(
            AuthoritativePaymentCommand(
                payment_id="pay_001",
                expected_version=2,
                source=PaymentSource.BEAM,
                paid_at=paid_at,
                provider_resource_id="beam_charge_002",
            )
        )
