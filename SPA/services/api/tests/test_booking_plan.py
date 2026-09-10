from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ValidationDomainError
from app.domains.bookings.plan import build_booking_plan, capacity_bucket_demands

VARIANTS = {
    "thai-60": ("thai", "นวดไทย", "Thai Massage", 60, 30000, "PER_PARTICIPANT", 1),
    "aroma-90": ("aroma", "อโรมา", "Aroma Therapy", 90, 60000, "PER_PARTICIPANT", 1),
    "couple-90": (
        "couple",
        "แพ็กเกจคู่",
        "Couple Package",
        90,
        119000,
        "PER_BOOKING",
        2,
    ),
}


def resolve_variant(variant_id: str):
    service_id, name_th, name_en, duration, price, mode, pax = VARIANTS[variant_id]
    return SimpleNamespace(id=service_id, name_th=name_th, name_en=name_en), SimpleNamespace(
        id=variant_id,
        duration_minutes=duration,
        price_satang=price,
        pricing_mode=mode,
        required_pax=pax,
    )


def participant(*variant_ids: str) -> dict[str, object]:
    return {"services": [{"serviceVariantId": item} for item in variant_ids]}


def test_multi_service_plan_is_sequential_per_participant_and_parallel_between_them() -> None:
    plan = build_booking_plan(
        [participant("thai-60", "aroma-90"), participant("aroma-90")],
        resolve_variant,
    )

    assert plan.participant_duration_minutes == (150, 90)
    assert plan.duration_minutes == 150
    assert plan.subtotal_satang == 150000
    assert [
        (line.participant_indexes, line.start_offset_minutes, line.end_offset_minutes)
        for line in plan.line_items
    ] == [((0,), 0, 60), ((1,), 0, 90), ((0,), 60, 150)]


def test_couple_package_is_one_shared_line_and_allows_individual_follow_up() -> None:
    plan = build_booking_plan(
        [participant("couple-90", "thai-60"), participant("couple-90", "aroma-90")],
        resolve_variant,
    )

    assert plan.subtotal_satang == 209000
    assert plan.participant_duration_minutes == (150, 180)
    assert plan.line_items[0].participant_indexes == (0, 1)
    assert plan.line_items[0].line_total_satang == 119000
    assert len(plan.line_items) == 3


@pytest.mark.parametrize(
    "participants",
    [
        [participant("couple-90")],
        [participant("couple-90"), participant("thai-60")],
        [participant("thai-60", "couple-90"), participant("thai-60", "couple-90")],
    ],
)
def test_invalid_package_combinations_are_rejected(
    participants: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationDomainError):
        build_booking_plan(participants, resolve_variant)


def test_capacity_demand_releases_shorter_participant_earlier_and_includes_buffer() -> None:
    start = datetime(2026, 9, 12, 10, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
    demands = capacity_bucket_demands(start, [60, 90], 15)

    assert list(demands.values()) == [2, 2, 2, 2, 2, 1, 1]
