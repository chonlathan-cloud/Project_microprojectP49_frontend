from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ValidationDomainError


@dataclass(frozen=True, slots=True)
class DailyCompensation:
    service_pay_satang: int
    tip_satang: int
    guarantee_rate_satang: int
    guarantee_top_up_satang: int
    shop_adjustment_satang: int
    total_earned_satang: int


def _validate_whole_baht(name: str, value: int, *, allow_negative: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationDomainError(f"{name} must be integer satang")
    if not allow_negative and value < 0:
        raise ValidationDomainError(f"{name} cannot be negative")
    if value % 100 != 0:
        raise ValidationDomainError(f"{name} must be a whole-baht amount")


def calculate_daily_compensation(
    *,
    present: bool,
    service_pay_satang: int,
    tip_satang: int,
    guarantee_rate_satang: int,
    shop_adjustment_satang: int = 0,
) -> DailyCompensation:
    """Calculate a daily guarantee without allowing tips to offset the guarantee."""

    _validate_whole_baht("Service pay", service_pay_satang)
    _validate_whole_baht("Tip", tip_satang)
    _validate_whole_baht("Guarantee rate", guarantee_rate_satang)
    _validate_whole_baht(
        "Shop adjustment", shop_adjustment_satang, allow_negative=True
    )
    guarantee_top_up = (
        max(0, guarantee_rate_satang - service_pay_satang) if present else 0
    )
    return DailyCompensation(
        service_pay_satang=service_pay_satang,
        tip_satang=tip_satang,
        guarantee_rate_satang=guarantee_rate_satang,
        guarantee_top_up_satang=guarantee_top_up,
        shop_adjustment_satang=shop_adjustment_satang,
        total_earned_satang=(
            service_pay_satang
            + tip_satang
            + guarantee_top_up
            + shop_adjustment_satang
        ),
    )
