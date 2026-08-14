from dataclasses import dataclass

from app.core.errors import ValidationDomainError
from app.core.types import PricingMode


@dataclass(frozen=True, slots=True)
class VariantSelection:
    participant_index: int
    variant_id: str
    unit_price_satang: int
    pricing_mode: PricingMode
    required_pax: int


@dataclass(frozen=True, slots=True)
class PriceLineItem:
    variant_id: str
    participant_indexes: tuple[int, ...]
    quantity: int
    line_total_satang: int


def price_booking(selections: list[VariantSelection]) -> tuple[list[PriceLineItem], int]:
    if not 1 <= len(selections) <= 2:
        raise ValidationDomainError("A booking must contain one or two participants")

    grouped: dict[str, list[VariantSelection]] = {}
    for selection in selections:
        if selection.unit_price_satang < 0:
            raise ValidationDomainError("Price cannot be negative")
        grouped.setdefault(selection.variant_id, []).append(selection)

    items: list[PriceLineItem] = []
    for variant_id, group in grouped.items():
        exemplar = group[0]
        if any(
            item.pricing_mode != exemplar.pricing_mode
            or item.unit_price_satang != exemplar.unit_price_satang
            or item.required_pax != exemplar.required_pax
            for item in group
        ):
            raise ValidationDomainError("Variant snapshot data is inconsistent")

        if exemplar.pricing_mode is PricingMode.PER_BOOKING:
            if len(group) != exemplar.required_pax:
                raise ValidationDomainError("A per-booking package must cover its required pax")
            quantity = 1
        else:
            if exemplar.required_pax != 1:
                raise ValidationDomainError("Per-participant variants must require one participant")
            quantity = len(group)

        items.append(
            PriceLineItem(
                variant_id=variant_id,
                participant_indexes=tuple(sorted(item.participant_index for item in group)),
                quantity=quantity,
                line_total_satang=exemplar.unit_price_satang * quantity,
            )
        )

    items.sort(key=lambda item: item.participant_indexes)
    return items, sum(item.line_total_satang for item in items)
