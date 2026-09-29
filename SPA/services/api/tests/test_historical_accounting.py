from app.infrastructure.firestore_accounting import (
    _historical_amounts,
    _historical_blocking_reason,
    _page_summary,
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


def test_cancelled_historical_export_is_visible_but_excluded_from_page_totals() -> None:
    summary = _page_summary(
        [
            {
                "exportStatus": "READY",
                "paymentSource": "BANK_TRANSFER",
                "grossAmountSatang": 30_000,
                "serviceAmountSatang": 25_000,
                "tipAmountSatang": 5_000,
            },
            {
                "exportStatus": "CANCELLED",
                "paymentSource": "CASH",
                "grossAmountSatang": 40_000,
                "serviceAmountSatang": 40_000,
                "tipAmountSatang": 0,
            },
        ]
    )

    assert summary["paidGrossSatang"] == 30_000
    assert summary["bankTransferGrossSatang"] == 30_000
    assert summary["cashGrossSatang"] == 0
    assert summary["serviceAmountSatang"] == 25_000
    assert summary["tipAmountSatang"] == 5_000
