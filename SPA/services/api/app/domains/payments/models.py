from dataclasses import dataclass, replace
from datetime import datetime

from app.core.errors import FinancialConflict, FinancialInvariantError
from app.core.types import (
    CashSettlementStatus,
    PaymentPurpose,
    PaymentSource,
    PaymentStatus,
)


@dataclass(frozen=True, slots=True)
class MoneyBreakdown:
    service_amount_satang: int
    tip_amount_satang: int
    gross_amount_satang: int
    currency: str = "THB"

    def __post_init__(self) -> None:
        amounts = (
            self.service_amount_satang,
            self.tip_amount_satang,
            self.gross_amount_satang,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in amounts):
            raise FinancialInvariantError("Financial amounts must be integer satang")
        if self.service_amount_satang <= 0:
            raise FinancialInvariantError("Service amount must be greater than zero")
        if self.tip_amount_satang < 0:
            raise FinancialInvariantError("Tip amount cannot be negative")
        if self.gross_amount_satang != self.service_amount_satang + self.tip_amount_satang:
            raise FinancialInvariantError("Gross amount must equal service amount plus tip")
        if self.currency != "THB":
            raise FinancialInvariantError("SPA customer payments must use THB")


@dataclass(frozen=True, slots=True)
class ServiceLineSnapshot:
    sku: str
    name: str
    quantity: int
    unit_price_satang: int

    def __post_init__(self) -> None:
        if not self.sku.strip() or not self.name.strip():
            raise FinancialInvariantError("Service line SKU and name are required")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise FinancialInvariantError("Service line quantity must be an integer")
        if self.quantity <= 0:
            raise FinancialInvariantError("Service line quantity must be positive")
        if isinstance(self.unit_price_satang, bool) or not isinstance(self.unit_price_satang, int):
            raise FinancialInvariantError("Service unit price must be integer satang")
        if self.unit_price_satang <= 0:
            raise FinancialInvariantError("Service unit price must be positive")

    @property
    def line_total_satang(self) -> int:
        return self.quantity * self.unit_price_satang


@dataclass(frozen=True, slots=True)
class Payment:
    payment_id: str
    booking_doc_id: str
    booking_public_id: str
    branch_id: str
    amounts: MoneyBreakdown
    service_lines: tuple[ServiceLineSnapshot, ...]
    subtotal_amount_satang: int | None = None
    discount_amount_satang: int = 0
    discount_reason: str | None = None
    status: PaymentStatus = PaymentStatus.DUE
    purpose: PaymentPurpose = PaymentPurpose.CUSTOMER_SALE
    source: PaymentSource | None = None
    paid_at: datetime | None = None
    provider_resource_id: str | None = None
    cash_received_by: str | None = None
    manual_received_by: str | None = None
    bank_account_key: str | None = None
    bank_account_id: str | None = None
    transfer_bank_account_id: str | None = None
    bank_account_label: str | None = None
    cash_settlement_status: CashSettlementStatus = CashSettlementStatus.NOT_APPLICABLE
    version: int = 1

    def __post_init__(self) -> None:
        if not self.service_lines:
            raise FinancialInvariantError("At least one immutable service line is required")
        line_subtotal = sum(line.line_total_satang for line in self.service_lines)
        subtotal = self.subtotal_amount_satang
        if subtotal is None:
            object.__setattr__(self, "subtotal_amount_satang", line_subtotal)
            subtotal = line_subtotal
        if isinstance(subtotal, bool) or not isinstance(subtotal, int) or subtotal <= 0:
            raise FinancialInvariantError("Service subtotal must be positive integer satang")
        if line_subtotal != subtotal:
            raise FinancialInvariantError(
                "Service line totals must equal the service subtotal snapshot"
            )
        if (
            isinstance(self.discount_amount_satang, bool)
            or not isinstance(self.discount_amount_satang, int)
            or self.discount_amount_satang < 0
            or self.discount_amount_satang >= subtotal
        ):
            raise FinancialInvariantError("Discount must be between zero and the service subtotal")
        if self.amounts.service_amount_satang != subtotal - self.discount_amount_satang:
            raise FinancialInvariantError(
                "Service amount must equal subtotal minus discount"
            )
        if self.discount_reason is not None and not isinstance(self.discount_reason, str):
            raise FinancialInvariantError("Discount reason must be text")
        if self.discount_amount_satang > 0 and not (self.discount_reason or "").strip():
            raise FinancialInvariantError("Discount reason is required")
        if self.discount_amount_satang == 0 and self.discount_reason is not None:
            raise FinancialInvariantError("Discount reason requires a discount amount")

    def mark_paid(
        self,
        *,
        source: PaymentSource,
        paid_at: datetime,
        provider_resource_id: str | None = None,
        cash_received_by: str | None = None,
        manual_received_by: str | None = None,
        bank_account_key: str | None = None,
        bank_account_id: str | None = None,
        transfer_bank_account_id: str | None = None,
        bank_account_label: str | None = None,
    ) -> "Payment":
        if paid_at.tzinfo is None or paid_at.utcoffset() is None:
            raise FinancialInvariantError("Authoritative paid time must be timezone-aware")
        if self.purpose is not PaymentPurpose.CUSTOMER_SALE:
            raise FinancialInvariantError("Cash-deposit settlements are not customer payments")
        if source is PaymentSource.BEAM and not provider_resource_id:
            raise FinancialInvariantError("Beam success requires a provider resource ID")
        if source is PaymentSource.CASH and not cash_received_by:
            raise FinancialInvariantError("Cash receipt requires an authorized actor")
        if source is PaymentSource.BANK_TRANSFER and not manual_received_by:
            raise FinancialInvariantError("Bank transfer requires an authorized actor")
        bank_fields = (
            bank_account_key,
            bank_account_id,
            transfer_bank_account_id,
            bank_account_label,
        )
        if source is PaymentSource.BANK_TRANSFER and not all(bank_fields):
            raise FinancialInvariantError("Bank transfer requires an account snapshot")
        if source is not PaymentSource.BANK_TRANSFER and any(bank_fields):
            raise FinancialInvariantError("Bank account evidence is only valid for bank transfer")

        if self.status is PaymentStatus.PAID:
            if (
                self.source is source
                and self.paid_at == paid_at
                and self.provider_resource_id == provider_resource_id
                and self.cash_received_by == cash_received_by
                and self.manual_received_by == manual_received_by
                and self.bank_account_key == bank_account_key
                and self.bank_account_id == bank_account_id
                and self.transfer_bank_account_id == transfer_bank_account_id
                and self.bank_account_label == bank_account_label
            ):
                return self
            raise FinancialConflict("Payment is already paid with different evidence")
        if self.status not in {PaymentStatus.DUE, PaymentStatus.PAYMENT_PENDING}:
            raise FinancialConflict(f"Cannot pay a payment in {self.status} state")

        settlement_status = (
            CashSettlementStatus.UNSETTLED
            if source is PaymentSource.CASH
            else CashSettlementStatus.NOT_APPLICABLE
        )
        return replace(
            self,
            status=PaymentStatus.PAID,
            source=source,
            paid_at=paid_at,
            provider_resource_id=provider_resource_id,
            cash_received_by=cash_received_by,
            manual_received_by=manual_received_by,
            bank_account_key=bank_account_key,
            bank_account_id=bank_account_id,
            transfer_bank_account_id=transfer_bank_account_id,
            bank_account_label=bank_account_label,
            cash_settlement_status=settlement_status,
            version=self.version + 1,
        )
