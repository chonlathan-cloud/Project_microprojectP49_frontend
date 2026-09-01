from dataclasses import dataclass
from datetime import date, datetime

from app.core.types import (
    AccountingExportStatus,
    FlowAccountPaymentStrategy,
    PaymentSource,
)
from app.domains.payments.models import ServiceLineSnapshot


@dataclass(frozen=True, slots=True)
class AccountingExport:
    export_id: str
    export_key: str
    payment_id: str
    booking_doc_id: str
    booking_public_id: str
    branch_id: str
    business_unit_code: str
    project_name: str
    accounting_date: date
    paid_at: datetime
    payment_source: PaymentSource
    payment_strategy: FlowAccountPaymentStrategy
    service_amount_satang: int
    tip_amount_satang: int
    gross_amount_satang: int
    currency: str
    service_lines: tuple[ServiceLineSnapshot, ...]
    subtotal_amount_satang: int
    discount_amount_satang: int
    discount_reason: str | None
    external_reference: str
    external_document_id: str
    status: AccountingExportStatus = AccountingExportStatus.READY
    source_snapshot_version: int = 1
    attempt_count: int = 0
    flow_account_record_id: str | None = None
    flow_account_document_id: str | None = None
    flow_account_document_serial: str | None = None
