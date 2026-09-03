from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ValidationDomainError


@dataclass(frozen=True, slots=True)
class SettlementAllocation:
    participant_id: str
    therapist_id: str | None
    therapist_pay_satang: int
    tip_share_satang: int
    booking_line_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class SettlementTotals:
    net_service_amount_satang: int
    source_tip_amount_satang: int
    therapist_pay_satang: int
    therapist_tip_satang: int
    shop_service_amount_satang: int
    shop_tip_satang: int
    shop_total_satang: int
    negative_shop_service_amount: bool


def _validate_whole_baht(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationDomainError(f"{name} must be integer satang")
    if value < 0:
        raise ValidationDomainError(f"{name} cannot be negative")
    if value % 100 != 0:
        raise ValidationDomainError(f"{name} must be a whole-baht amount")


def calculate_settlement_totals(
    *,
    net_service_amount_satang: int,
    source_tip_amount_satang: int,
    allocations: tuple[SettlementAllocation, ...],
) -> SettlementTotals:
    _validate_whole_baht("Net service amount", net_service_amount_satang)
    _validate_whole_baht("Tip amount", source_tip_amount_satang)
    if net_service_amount_satang <= 0:
        raise ValidationDomainError("Net service amount must be greater than zero")
    if not allocations:
        raise ValidationDomainError("At least one participant allocation is required")

    allocation_keys: set[str] = set()
    therapist_pay_satang = 0
    therapist_tip_satang = 0
    for allocation in allocations:
        if not allocation.participant_id.strip():
            raise ValidationDomainError("Participant ID is required")
        allocation_key = allocation.booking_line_item_id or allocation.participant_id
        if allocation_key in allocation_keys:
            raise ValidationDomainError("Each service line can be allocated only once")
        allocation_keys.add(allocation_key)
        _validate_whole_baht("Therapist pay", allocation.therapist_pay_satang)
        _validate_whole_baht("Therapist tip share", allocation.tip_share_satang)
        if (
            allocation.therapist_pay_satang > 0 or allocation.tip_share_satang > 0
        ) and not allocation.therapist_id:
            raise ValidationDomainError(
                "A therapist is required when therapist pay or tip is greater than zero"
            )
        therapist_pay_satang += allocation.therapist_pay_satang
        therapist_tip_satang += allocation.tip_share_satang

    if therapist_tip_satang > source_tip_amount_satang:
        raise ValidationDomainError("Therapist tip shares cannot exceed the received tip")

    shop_service_amount_satang = net_service_amount_satang - therapist_pay_satang
    shop_tip_satang = source_tip_amount_satang - therapist_tip_satang
    return SettlementTotals(
        net_service_amount_satang=net_service_amount_satang,
        source_tip_amount_satang=source_tip_amount_satang,
        therapist_pay_satang=therapist_pay_satang,
        therapist_tip_satang=therapist_tip_satang,
        shop_service_amount_satang=shop_service_amount_satang,
        shop_tip_satang=shop_tip_satang,
        shop_total_satang=shop_service_amount_satang + shop_tip_satang,
        negative_shop_service_amount=shop_service_amount_satang < 0,
    )
