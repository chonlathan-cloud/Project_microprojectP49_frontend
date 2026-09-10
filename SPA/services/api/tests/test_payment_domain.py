from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.application.financial_ledger import (
    AuthoritativePaymentCommand,
    InMemoryFinancialLedger,
)
from app.application.payments import PaymentService
from app.core.errors import (
    FinancialConflict,
    FinancialInvariantError,
    PermissionDenied,
    ValidationDomainError,
)
from app.core.types import (
    AppRole,
    BookingStatus,
    CashSettlementStatus,
    PaymentSource,
    PaymentStatus,
)
from app.domains.accounting.factory import build_accounting_export
from app.domains.bookings.pricing import validate_fixed_discount
from app.domains.identity.models import AdminPrincipal
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
from app.infrastructure.firestore_payments import _export_data, _new_payment, _with_discount


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


def test_discounted_booking_freezes_subtotal_discount_and_net_payment() -> None:
    lines = (
        ServiceLineSnapshot(
            sku="FOOT-60",
            name="นวดเท้า 60 นาที",
            quantity=1,
            unit_price_satang=50_000,
        ),
    )
    discounted = _new_payment(
        "booking-doc-001",
        {
            "publicBookingId": "BK-20260901-001",
            "branchId": "branch_001",
            "subtotalAmountSatang": 50_000,
            "discountAmountSatang": 2_000,
            "discountReason": "คูปองสมัครครั้งแรก",
            "estimatedAmountSatang": 48_000,
        },
        lines,
    )

    assert discounted.subtotal_amount_satang == 50_000
    assert discounted.discount_amount_satang == 2_000
    assert discounted.amounts.service_amount_satang == 48_000
    assert discounted.service_lines[0].unit_price_satang == 50_000
    paid = discounted.mark_paid(
        source=PaymentSource.CASH,
        paid_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        cash_received_by="admin-001",
    )
    accounting_export = build_accounting_export(paid)
    assert accounting_export.subtotal_amount_satang == 50_000
    assert accounting_export.discount_amount_satang == 2_000
    assert accounting_export.service_amount_satang == 48_000


def test_discounted_booking_rejects_tampered_net_amount() -> None:
    lines = (ServiceLineSnapshot("FOOT-60", "Foot massage", 1, 50_000),)
    with pytest.raises(FinancialConflict, match="payable snapshot"):
        _new_payment(
            "booking-doc-001",
            {
                "publicBookingId": "BK-20260901-001",
                "branchId": "branch_001",
                "subtotalAmountSatang": 50_000,
                "discountAmountSatang": 2_000,
                "discountReason": "คูปองสมัครครั้งแรก",
                "estimatedAmountSatang": 49_000,
            },
            lines,
        )


def test_completed_booking_discount_preserves_lines_and_tip() -> None:
    current = payment()
    discounted = _with_discount(
        current,
        discount_amount_satang=5_000,
        reason="  ลูกค้าประจำ  ",
    )

    assert discounted.subtotal_amount_satang == 35_000
    assert discounted.discount_amount_satang == 5_000
    assert discounted.discount_reason == "ลูกค้าประจำ"
    assert discounted.amounts.service_amount_satang == 30_000
    assert discounted.amounts.tip_amount_satang == 5_000
    assert discounted.amounts.gross_amount_satang == 35_000
    assert discounted.service_lines == current.service_lines
    assert discounted.version == current.version + 1


def test_booking_discount_requires_whole_baht_and_a_reason() -> None:
    with pytest.raises(ValidationDomainError):
        _with_discount(payment(), discount_amount_satang=5_050, reason="ทดสอบ")
    with pytest.raises(ValidationDomainError):
        _with_discount(payment(), discount_amount_satang=35_000, reason="ทดสอบ")
    with pytest.raises(ValidationDomainError):
        _with_discount(payment(), discount_amount_satang=5_000, reason=" ")


def test_removing_discount_requires_audit_reason_but_stores_no_discount_reason() -> None:
    discounted = _with_discount(
        payment(),
        discount_amount_satang=5_000,
        reason="ลูกค้าประจำ",
    )
    restored = _with_discount(
        discounted,
        discount_amount_satang=0,
        reason="Admin บันทึกผิด",
    )

    assert restored.discount_amount_satang == 0
    assert restored.discount_reason is None
    assert validate_fixed_discount(
        subtotal_amount_satang=35_000,
        discount_amount_satang=0,
        reason="Admin บันทึกผิด",
    ) == "Admin บันทึกผิด"


@pytest.mark.asyncio
async def test_post_service_discount_is_admin_only() -> None:
    service = PaymentService(object(), object())  # type: ignore[arg-type]
    with pytest.raises(PermissionDenied, match="ADMIN"):
        await service.update_booking_discount(
            booking_public_id="BK-001",
            principal=AdminPrincipal(
                uid="staff-001",
                email="staff@example.com",
                role=AppRole.STAFF,
                branch_ids=("branch_001",),
            ),
            discount_amount_satang=5_000,
            reason="ลูกค้าประจำ",
            expected_booking_version=4,
        )


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


def test_same_day_payments_create_distinct_exports_instead_of_daily_aggregation() -> None:
    ledger = InMemoryFinancialLedger()
    first_payment = payment()
    second_payment = replace(
        payment(),
        payment_id="pay_002",
        booking_doc_id="booking-doc-002",
        booking_public_id="BK-20260831-002",
    )
    ledger.add_payment(first_payment)
    ledger.add_payment(second_payment)
    paid_at = datetime(2026, 8, 31, 14, 10, tzinfo=UTC)

    first = ledger.commit_authoritative_payment(
        AuthoritativePaymentCommand(
            payment_id="pay_001",
            expected_version=1,
            source=PaymentSource.BEAM,
            paid_at=paid_at,
            provider_resource_id="beam_charge_001",
        )
    )
    second = ledger.commit_authoritative_payment(
        AuthoritativePaymentCommand(
            payment_id="pay_002",
            expected_version=1,
            source=PaymentSource.BEAM,
            paid_at=paid_at,
            provider_resource_id="beam_charge_002",
        )
    )

    assert (
        first.accounting_export.accounting_date
        == second.accounting_export.accounting_date
    )
    assert first.accounting_export.export_key != second.accounting_export.export_key
    assert first.accounting_export.export_id != second.accounting_export.export_id
    assert (
        first.accounting_export.external_document_id
        != second.accounting_export.external_document_id
    )
    assert len(ledger.exports()) == 2


def test_export_snapshot_persists_versioned_flowaccount_contract_metadata() -> None:
    paid = payment().mark_paid(
        source=PaymentSource.CASH,
        paid_at=datetime(2026, 8, 31, 14, 10, tzinfo=UTC),
        cash_received_by="admin_001",
    )
    snapshot = _export_data(
        build_accounting_export(paid),
        datetime(2026, 8, 31, 14, 11, tzinfo=UTC),
    )

    assert snapshot["provider"] == "FLOWACCOUNT"
    assert snapshot["documentIntent"] == "CASH_INVOICE_WITH_PAYMENT"
    assert snapshot["flowAccountContactStrategy"] == "SPA49_WALKIN"
    assert snapshot["flowAccountPaymentStrategy"] == "CASH"
    assert snapshot["vatPolicyVersion"] == "SPA_VAT_INCLUSIVE_7_V1"
    assert "paymentStrategy" not in snapshot


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


def test_bank_transfer_is_paid_without_cash_settlement() -> None:
    paid = payment().mark_paid(
        source=PaymentSource.BANK_TRANSFER,
        paid_at=datetime(2026, 8, 31, 14, 10, tzinfo=UTC),
        manual_received_by="admin-001",
        bank_account_key="kbank-6073-a",
        bank_account_id="462850",
        transfer_bank_account_id="2",
        bank_account_label="KBank ••••6073 · Company (บัญชี A)",
    )
    accounting_export = build_accounting_export(paid)

    assert paid.status is PaymentStatus.PAID
    assert paid.cash_settlement_status is CashSettlementStatus.NOT_APPLICABLE
    assert accounting_export.payment_source is PaymentSource.BANK_TRANSFER
    assert accounting_export.payment_strategy == "BANK_TRANSFER"
    assert accounting_export.bank_account_id == "462850"


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
