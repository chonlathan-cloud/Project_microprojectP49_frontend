from dataclasses import dataclass
from datetime import datetime

from app.core.errors import FinancialConflict, FinancialInvariantError
from app.integrations.beam import BeamCharge


@dataclass(frozen=True, slots=True)
class CashDepositChargeSnapshot:
    total_amount_satang: int
    currency: str
    provider_reference_id: str
    attempt_created_at: datetime
    attempt_expires_at: datetime


def validate_cash_deposit_charge(
    charge: BeamCharge,
    snapshot: CashDepositChargeSnapshot,
    *,
    expected_merchant_id: str,
) -> datetime:
    if charge.status != "SUCCEEDED" or charge.transaction_time is None:
        raise FinancialConflict("Beam cash-deposit charge is not an authoritative success")
    if charge.merchant_id != expected_merchant_id:
        raise FinancialConflict("Beam merchant does not match configured merchant")
    if charge.reference_id != snapshot.provider_reference_id:
        raise FinancialConflict("Beam reference does not match cash-deposit attempt")
    if charge.currency != snapshot.currency:
        raise FinancialConflict("Beam currency does not match cash-deposit snapshot")
    if isinstance(charge.amount, bool) or not isinstance(charge.amount, int):
        raise FinancialInvariantError("Beam amount must be integer satang")
    if charge.amount != snapshot.total_amount_satang:
        raise FinancialConflict("Beam amount does not match cash-deposit snapshot")
    if not snapshot.attempt_created_at <= charge.transaction_time <= snapshot.attempt_expires_at:
        raise FinancialConflict("Beam transaction is outside the cash-deposit attempt window")
    return charge.transaction_time
