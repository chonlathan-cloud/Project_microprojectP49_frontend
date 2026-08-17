import pytest

from app.core.errors import ValidationDomainError
from app.domains.bookings.service import mask_phone, normalize_thai_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0643654949", "+66643654949"),
        ("064-365-4949", "+66643654949"),
        ("+66 64 365 4949", "+66643654949"),
    ],
)
def test_normalize_thai_phone(raw: str, expected: str) -> None:
    assert normalize_thai_phone(raw) == expected


def test_invalid_phone_is_rejected() -> None:
    with pytest.raises(ValidationDomainError):
        normalize_thai_phone("123")


def test_phone_mask_does_not_expose_full_number() -> None:
    masked = mask_phone("+66643654949")
    assert masked == "064-xxx-4949"
    assert "365" not in masked
