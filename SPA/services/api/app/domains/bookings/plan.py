from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.core.errors import ValidationDomainError
from app.domains.capacity.buckets import required_bucket_starts


@dataclass(frozen=True)
class PlannedSelection:
    participant_index: int
    service_index: int
    participant: dict[str, object]
    service: object
    variant: object
    start_offset_minutes: int
    end_offset_minutes: int


@dataclass(frozen=True)
class PlannedLineItem:
    participant_indexes: tuple[int, ...]
    selection: PlannedSelection
    start_offset_minutes: int
    end_offset_minutes: int
    line_total_satang: int


@dataclass(frozen=True)
class BookingPlan:
    participant_selections: tuple[tuple[PlannedSelection, ...], ...]
    line_items: tuple[PlannedLineItem, ...]
    participant_duration_minutes: tuple[int, ...]
    duration_minutes: int
    subtotal_satang: int


def _pricing_mode(variant: object) -> str:
    value = getattr(variant, "pricing_mode", "")
    return str(getattr(value, "value", value))


def _variant_ids(participant: dict[str, object]) -> list[str]:
    legacy = str(participant.get("serviceVariantId") or "").strip()
    raw_services = participant.get("services")
    if raw_services:
        if legacy:
            raise ValidationDomainError("A participant cannot mix serviceVariantId with services")
        if not isinstance(raw_services, list):
            raise ValidationDomainError("Participant services must be a list")
        values: list[str] = []
        for item in raw_services:
            if not isinstance(item, dict):
                raise ValidationDomainError("Each participant service must be an object")
            variant_id = str(item.get("serviceVariantId") or "").strip()
            if not variant_id:
                raise ValidationDomainError("A service variant is required")
            values.append(variant_id)
        return values
    if legacy:
        return [legacy]
    raise ValidationDomainError("At least one service is required for every participant")


def build_booking_plan(
    participants: Sequence[dict[str, object]],
    resolve_variant: Callable[[str], tuple[object, object]],
    *,
    max_services_per_participant: int = 3,
) -> BookingPlan:
    if len(participants) not in {1, 2}:
        raise ValidationDomainError("A booking must contain one or two participants")
    if max_services_per_participant < 1:
        raise ValueError("max_services_per_participant must be positive")

    participant_selections: list[tuple[PlannedSelection, ...]] = []
    for participant_index, participant in enumerate(participants):
        variant_ids = _variant_ids(participant)
        if len(variant_ids) > max_services_per_participant:
            raise ValidationDomainError(
                f"A participant may select at most {max_services_per_participant} services"
            )
        if len(set(variant_ids)) != len(variant_ids):
            raise ValidationDomainError(
                "The same service variant cannot be selected twice for one participant"
            )
        offset = 0
        selections: list[PlannedSelection] = []
        for service_index, variant_id in enumerate(variant_ids):
            service, variant = resolve_variant(variant_id)
            duration = int(variant.duration_minutes)
            if duration <= 0:
                raise ValidationDomainError("Service duration must be positive")
            selections.append(
                PlannedSelection(
                    participant_index=participant_index,
                    service_index=service_index,
                    participant=participant,
                    service=service,
                    variant=variant,
                    start_offset_minutes=offset,
                    end_offset_minutes=offset + duration,
                )
            )
            offset += duration
        participant_selections.append(tuple(selections))

    package_selections = [
        selection
        for selections in participant_selections
        for selection in selections
        if _pricing_mode(selection.variant) == "PER_BOOKING"
        or int(selection.variant.required_pax) > 1
    ]
    shared_variant_id: str | None = None
    if package_selections:
        first_variants = [selections[0].variant for selections in participant_selections]
        first_ids = {str(variant.id) for variant in first_variants}
        if (
            len(first_ids) != 1
            or len(participants) != int(first_variants[0].required_pax)
            or _pricing_mode(first_variants[0]) != "PER_BOOKING"
            or len(package_selections) != len(participants)
            or any(selection.service_index != 0 for selection in package_selections)
        ):
            raise ValidationDomainError(
                "A two-person package must be the identical first service for both participants"
            )
        shared_variant_id = str(first_variants[0].id)

    for selections in participant_selections:
        for selection in selections:
            mode = _pricing_mode(selection.variant)
            required_pax = int(selection.variant.required_pax)
            if mode == "PER_PARTICIPANT" and required_pax == 1:
                continue
            if (
                mode == "PER_BOOKING"
                and shared_variant_id == str(selection.variant.id)
                and selection.service_index == 0
            ):
                continue
            raise ValidationDomainError("Unsupported service pricing or pax configuration")

    line_items: list[PlannedLineItem] = []
    if shared_variant_id:
        selection = participant_selections[0][0]
        line_items.append(
            PlannedLineItem(
                participant_indexes=tuple(range(len(participants))),
                selection=selection,
                start_offset_minutes=selection.start_offset_minutes,
                end_offset_minutes=selection.end_offset_minutes,
                line_total_satang=int(selection.variant.price_satang),
            )
        )
    for participant_index, selections in enumerate(participant_selections):
        for selection in selections:
            if shared_variant_id and selection.service_index == 0:
                continue
            line_items.append(
                PlannedLineItem(
                    participant_indexes=(participant_index,),
                    selection=selection,
                    start_offset_minutes=selection.start_offset_minutes,
                    end_offset_minutes=selection.end_offset_minutes,
                    line_total_satang=int(selection.variant.price_satang),
                )
            )
    line_items.sort(
        key=lambda item: (
            item.start_offset_minutes,
            item.participant_indexes[0],
            item.selection.service_index,
        )
    )
    durations = tuple(selections[-1].end_offset_minutes for selections in participant_selections)
    return BookingPlan(
        participant_selections=tuple(participant_selections),
        line_items=tuple(line_items),
        participant_duration_minutes=durations,
        duration_minutes=max(durations),
        subtotal_satang=sum(item.line_total_satang for item in line_items),
    )


def capacity_bucket_demands(
    start_at: datetime,
    participant_duration_minutes: Sequence[int],
    buffer_minutes: int,
) -> dict[datetime, int]:
    demands: dict[datetime, int] = {}
    for duration in participant_duration_minutes:
        for bucket_start in required_bucket_starts(start_at, duration, buffer_minutes):
            demands[bucket_start] = demands.get(bucket_start, 0) + 1
    return dict(sorted(demands.items()))
