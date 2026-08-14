import pytest

from app.core.errors import ValidationDomainError
from app.core.types import PricingMode
from app.domains.bookings.pricing import VariantSelection, price_booking


def test_couple_package_is_charged_once_for_two_participants() -> None:
    selections = [
        VariantSelection(index, "couple-relaxation-90", 119000, PricingMode.PER_BOOKING, 2)
        for index in range(2)
    ]
    items, total = price_booking(selections)
    assert total == 119000
    assert items[0].quantity == 1
    assert items[0].participant_indexes == (0, 1)


def test_couple_package_rejects_one_participant() -> None:
    with pytest.raises(ValidationDomainError, match="required pax"):
        price_booking(
            [VariantSelection(0, "couple-relaxation-90", 119000, PricingMode.PER_BOOKING, 2)]
        )


def test_different_participant_services_are_summed() -> None:
    items, total = price_booking(
        [
            VariantSelection(0, "traditional-thai-60", 30000, PricingMode.PER_PARTICIPANT, 1),
            VariantSelection(1, "aroma-therapy-60", 60000, PricingMode.PER_PARTICIPANT, 1),
        ]
    )
    assert len(items) == 2
    assert total == 90000
