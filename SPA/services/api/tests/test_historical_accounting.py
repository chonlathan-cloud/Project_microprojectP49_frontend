from app.infrastructure.firestore_accounting import (
    _historical_amounts,
    _historical_blocking_reason,
)


def test_historical_amounts_use_persisted_gross_or_safe_fallback() -> None:
    assert _historical_amounts(
        {
            "estimatedAmountSatang": 30_000,
            "tipAmountSatang": 5_000,
            "grossAmountSatang": 35_000,
        }
    ) == (30_000, 5_000, 35_000)
    assert _historical_amounts(
        {"estimatedAmountSatang": 30_000, "tipAmountSatang": 5_000}
    ) == (30_000, 5_000, 35_000)


def test_zero_value_historical_record_is_visible_but_blocked_from_accounting() -> None:
    assert (
        _historical_blocking_reason(
            {
                "estimatedAmountSatang": 0,
                "tipAmountSatang": 0,
                "grossAmountSatang": 0,
            }
        )
        == "NON_POSITIVE_AMOUNT"
    )
    assert (
        _historical_blocking_reason(
            {
                "estimatedAmountSatang": 30_000,
                "tipAmountSatang": 0,
                "grossAmountSatang": 30_000,
            }
        )
        is None
    )
