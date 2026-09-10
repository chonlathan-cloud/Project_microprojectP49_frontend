from base64 import b32encode
from hashlib import sha256
from zoneinfo import ZoneInfo

from app.core.errors import FinancialInvariantError
from app.core.types import FlowAccountPaymentStrategy, PaymentSource, PaymentStatus
from app.domains.accounting.models import AccountingExport
from app.domains.payments.models import Payment

BANGKOK = ZoneInfo("Asia/Bangkok")


def _stable_digest(value: str, *, length: int) -> str:
    encoded = b32encode(sha256(value.encode("utf-8")).digest()).decode("ascii").rstrip("=")
    return encoded[:length]


def build_accounting_export(payment: Payment) -> AccountingExport:
    if payment.status is not PaymentStatus.PAID or payment.paid_at is None:
        raise FinancialInvariantError("Only an authoritative paid customer sale can be exported")
    if payment.source not in {
        PaymentSource.BEAM,
        PaymentSource.CASH,
        PaymentSource.BANK_TRANSFER,
    }:
        raise FinancialInvariantError("Payment source is required for accounting export")

    digest = _stable_digest(payment.payment_id, length=26)
    external_document_id = f"SPAPAY-{digest}"
    strategy = {
        PaymentSource.BEAM: FlowAccountPaymentStrategy.BEAM_OTHER_CHANNEL,
        PaymentSource.CASH: FlowAccountPaymentStrategy.CASH,
        PaymentSource.BANK_TRANSFER: FlowAccountPaymentStrategy.BANK_TRANSFER,
    }[payment.source]
    return AccountingExport(
        export_id=f"fa_{digest.lower()}",
        export_key=f"FLOWACCOUNT:CASH_INVOICE:{payment.payment_id}",
        payment_id=payment.payment_id,
        booking_doc_id=payment.booking_doc_id,
        booking_public_id=payment.booking_public_id,
        branch_id=payment.branch_id,
        business_unit_code="SPA-49",
        project_name="Spa 49",
        accounting_date=payment.paid_at.astimezone(BANGKOK).date(),
        paid_at=payment.paid_at,
        payment_source=payment.source,
        payment_strategy=strategy,
        service_amount_satang=payment.amounts.service_amount_satang,
        tip_amount_satang=payment.amounts.tip_amount_satang,
        gross_amount_satang=payment.amounts.gross_amount_satang,
        currency=payment.amounts.currency,
        service_lines=payment.service_lines,
        subtotal_amount_satang=(
            payment.subtotal_amount_satang
            if payment.subtotal_amount_satang is not None
            else payment.amounts.service_amount_satang
        ),
        discount_amount_satang=payment.discount_amount_satang,
        discount_reason=payment.discount_reason,
        external_reference=f"SPA-PAY-{payment.payment_id}",
        external_document_id=external_document_id,
        provider="FLOWACCOUNT",
        document_intent="CASH_INVOICE_WITH_PAYMENT",
        flow_account_contact_strategy="SPA49_WALKIN",
        vat_policy_version="SPA_VAT_INCLUSIVE_7_V1",
        source_snapshot_version=payment.version,
    )
