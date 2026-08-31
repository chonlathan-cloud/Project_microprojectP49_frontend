from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from app.core.errors import FinancialConflict
from app.core.types import PaymentSource
from app.domains.accounting.factory import build_accounting_export
from app.domains.accounting.models import AccountingExport
from app.domains.payments.models import Payment


@dataclass(frozen=True, slots=True)
class AuthoritativePaymentCommand:
    payment_id: str
    expected_version: int
    source: PaymentSource
    paid_at: datetime
    provider_resource_id: str | None = None
    cash_received_by: str | None = None


@dataclass(frozen=True, slots=True)
class AuthoritativePaymentResult:
    payment: Payment
    accounting_export: AccountingExport
    replayed: bool


class InMemoryFinancialLedger:
    """Transactional reference adapter used by tests and local composition.

    Production must provide the same compare-and-create semantics in one Firestore transaction.
    """

    def __init__(self) -> None:
        self._payments: dict[str, Payment] = {}
        self._exports_by_key: dict[str, AccountingExport] = {}
        self._lock = RLock()

    def add_payment(self, payment: Payment) -> None:
        with self._lock:
            if payment.payment_id in self._payments:
                raise FinancialConflict("Payment already exists")
            self._payments[payment.payment_id] = payment

    def commit_authoritative_payment(
        self, command: AuthoritativePaymentCommand
    ) -> AuthoritativePaymentResult:
        with self._lock:
            current = self._payments.get(command.payment_id)
            if current is None:
                raise FinancialConflict("Payment does not exist")

            replay_candidate = current.mark_paid(
                source=command.source,
                paid_at=command.paid_at,
                provider_resource_id=command.provider_resource_id,
                cash_received_by=command.cash_received_by,
            )
            replayed = replay_candidate is current
            if not replayed and current.version != command.expected_version:
                raise FinancialConflict("Payment version changed")

            export = build_accounting_export(replay_candidate)
            existing_export = self._exports_by_key.get(export.export_key)
            if existing_export is not None and existing_export != export:
                raise FinancialConflict("Accounting export snapshot conflicts with existing record")

            self._payments[command.payment_id] = replay_candidate
            self._exports_by_key.setdefault(export.export_key, export)
            return AuthoritativePaymentResult(
                payment=replay_candidate,
                accounting_export=self._exports_by_key[export.export_key],
                replayed=replayed,
            )

    def get_payment(self, payment_id: str) -> Payment | None:
        with self._lock:
            return self._payments.get(payment_id)

    def exports(self) -> tuple[AccountingExport, ...]:
        with self._lock:
            return tuple(self._exports_by_key.values())
