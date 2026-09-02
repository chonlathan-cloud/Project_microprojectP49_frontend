from __future__ import annotations

from datetime import date

import pytest

from scripts.enable_test_historical_analytics import (
    FIXTURE_KIND,
    SourceDocument,
    build_plan,
    parse_args,
    plan_digest,
)

FROM_DATE = date(2026, 8, 1)
TO_DATE = date(2026, 8, 31)


def fixture(document_id: str, **overrides: object) -> SourceDocument:
    data = {
        "localDate": "2026-08-15",
        "status": "RECORDED",
        "adminEntryMode": "HISTORICAL_RECORD",
        "historicalFinancialRecord": True,
        "financiallyExcluded": True,
        "estimatedAmountSatang": 60_000,
        "testFixture": {"kind": FIXTURE_KIND},
    }
    data.update(overrides)
    return SourceDocument(document_id, data)


def line(document_id: str, booking_id: str, **overrides: object) -> SourceDocument:
    data = {
        "bookingDocId": booking_id,
        "financiallyExcluded": True,
        "testFixture": {"kind": FIXTURE_KIND},
    }
    data.update(overrides)
    return SourceDocument(document_id, data)


def test_plan_selects_only_excluded_recorded_historical_fixtures() -> None:
    bookings = [
        fixture("eligible"),
        fixture("already-enabled", financiallyExcluded=False),
        fixture("cancelled", status="CANCELLED"),
        fixture("normal-test", testFixture={"kind": "OTHER"}),
    ]
    plan = build_plan(
        bookings,
        [line("line-1", "eligible")],
        from_date=FROM_DATE,
        to_date=TO_DATE,
    )

    assert plan.booking_ids == ("eligible",)
    assert plan.line_item_ids == ("line-1",)
    assert plan.net_service_amount_satang == 60_000
    assert plan.write_count == 3


def test_plan_is_deterministic() -> None:
    first = build_plan(
        [fixture("booking-1")],
        [line("line-1", "booking-1")],
        from_date=FROM_DATE,
        to_date=TO_DATE,
    )
    second = build_plan(
        [fixture("booking-1")],
        [line("line-1", "booking-1")],
        from_date=FROM_DATE,
        to_date=TO_DATE,
    )

    assert plan_digest(first) == plan_digest(second)


def test_plan_rejects_missing_or_non_fixture_lines() -> None:
    with pytest.raises(ValueError, match="no Booking line items"):
        build_plan(
            [fixture("booking-1")],
            [],
            from_date=FROM_DATE,
            to_date=TO_DATE,
        )
    with pytest.raises(ValueError, match="non-fixture"):
        build_plan(
            [fixture("booking-1")],
            [line("line-1", "booking-1", testFixture={"kind": "OTHER"})],
            from_date=FROM_DATE,
            to_date=TO_DATE,
        )


def test_apply_requires_exact_test_database_and_reviewed_digest() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--from-date",
                "2026-08-01",
                "--to-date",
                "2026-08-31",
                "--apply",
                "--confirm-database",
                "spa-db",
                "--confirm-plan",
                "digest",
            ]
        )
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--from-date",
                "2026-08-01",
                "--to-date",
                "2026-08-31",
                "--apply",
                "--confirm-database",
                "spa-test-db",
            ]
        )
