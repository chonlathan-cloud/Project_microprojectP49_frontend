from __future__ import annotations

import re

from app.core.errors import ValidationDomainError


def normalize_thai_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("66"):
        digits = "0" + digits[2:]
    if len(digits) != 10 or not digits.startswith("0"):
        raise ValidationDomainError("A valid Thai phone number is required")
    return f"+66{digits[1:]}"


def mask_phone(e164: str) -> str:
    return f"0{e164[3:5]}-xxx-{e164[-4:]}"
