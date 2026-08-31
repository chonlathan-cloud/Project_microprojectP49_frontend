from enum import StrEnum

from app.core.errors import FinancialInvariantError
from app.core.types import AppRole

TIP_PRESETS_SATANG = (0, 2_000, 5_000, 10_000)


class AdminFinancialAction(StrEnum):
    RECORD_CASH = "RECORD_CASH"
    CASH_DEPOSIT = "CASH_DEPOSIT"
    LATE_OVERRIDE = "LATE_OVERRIDE"
    REFUND = "REFUND"
    CORRECTION = "CORRECTION"


def validate_tip_amount(tip_amount_satang: int, *, custom_max_satang: int | None) -> None:
    if not isinstance(tip_amount_satang, int) or isinstance(tip_amount_satang, bool):
        raise FinancialInvariantError("Tip amount must be integer satang")
    if tip_amount_satang < 0:
        raise FinancialInvariantError("Tip amount cannot be negative")
    if tip_amount_satang in TIP_PRESETS_SATANG:
        return
    if custom_max_satang is None or custom_max_satang <= 0:
        raise FinancialInvariantError("Custom tip is disabled until its maximum is configured")
    if tip_amount_satang > custom_max_satang:
        raise FinancialInvariantError("Custom tip exceeds the configured maximum")


def require_admin_financial_action(
    *,
    role: AppRole,
    action: AdminFinancialAction,
    reason: str | None = None,
) -> str | None:
    if role is not AppRole.ADMIN:
        raise FinancialInvariantError("ADMIN role is required for this financial action")
    if action in {AdminFinancialAction.REFUND, AdminFinancialAction.CORRECTION}:
        normalized_reason = reason.strip() if reason else ""
        if not normalized_reason:
            raise FinancialInvariantError("Refund and correction require a reason")
        return normalized_reason
    return None
