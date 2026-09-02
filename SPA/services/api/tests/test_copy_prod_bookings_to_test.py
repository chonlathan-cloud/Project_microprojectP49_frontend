from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from scripts.copy_prod_bookings_to_test import (
    FORBIDDEN_KEYS,
    SourceDocument,
    build_plan,
    parse_args,
    plan_digest,
)

RUN_ID = "prod-bookings-20260802-20260901-v1"
FROM_DATE = date(2026, 8, 2)
TO_DATE = date(2026, 9, 1)
NOW = datetime(2026, 8, 2, 3, 0, tzinfo=UTC)


def source_documents():
    bookings = [
        SourceDocument(
            "prod-booking-1",
            {
                "publicBookingId": "BK-REAL-001",
                "branchId": "branch_001",
                "source": "GUEST_WEB",
                "status": "COMPLETED",
                "customerListBucket": "HISTORY",
                "contact": {
                    "mode": "PHONE",
                    "phoneE164": "+66812345678",
                    "phoneMasked": "081***678",
                },
                "customerName": "Real Customer",
                "lineIdentityHash": "private-hash",
                "statusTokenHash": "secret-token-hash",
                "recordedBy": "admin@example.com",
                "serviceName": "Thai Massage",
                "serviceId": "service-1",
                "startAt": NOW,
                "endAt": NOW,
                "localDate": "2026-08-02",
                "localStartTime": "10:00",
                "timezone": "Asia/Bangkok",
                "pax": 1,
                "subtotalAmountSatang": 100_000,
                "discountAmountSatang": 0,
                "estimatedAmountSatang": 100_000,
                "tipAmountSatang": 0,
                "grossAmountSatang": 100_000,
                "createdAt": NOW,
                "updatedAt": NOW,
            },
        )
    ]
    participants = [
        SourceDocument(
            "prod-participant-1",
            {
                "bookingDocId": "prod-booking-1",
                "branchId": "branch_001",
                "sequence": 1,
                "nickname": "Sensitive Nickname",
                "healthAlert": True,
                "healthProfileId": "prod-health-1",
                "createdAt": NOW,
            },
        )
    ]
    line_items = [
        SourceDocument(
            "prod-line-1",
            {
                "bookingDocId": "prod-booking-1",
                "branchId": "branch_001",
                "serviceSnapshot": {
                    "serviceId": "service-1",
                    "variantId": "variant-1",
                    "nameTh": "นวดไทย",
                    "nameEn": "Thai Massage",
                    "durationMinutes": 60,
                    "pricingMode": "PER_PARTICIPANT",
                    "requiredPax": 1,
                    "unitPriceSatang": 100_000,
                    "internalNote": "must not copy",
                },
                "quantity": 1,
                "lineTotalSatang": 100_000,
                "participantIds": ["prod-participant-1"],
                "createdAt": NOW,
            },
        )
    ]
    return bookings, line_items, participants


def make_plan():
    bookings, lines, participants = source_documents()
    return build_plan(
        bookings,
        lines,
        participants,
        from_date=FROM_DATE,
        to_date=TO_DATE,
        run_id=RUN_ID,
    )


def walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_keys(nested)


def test_plan_anonymizes_identity_and_health_and_excludes_financial_side_effects() -> None:
    plan = make_plan()
    booking = next(write for write in plan.writes if write.collection == "bookings")
    participant = next(
        write for write in plan.writes if write.collection == "booking_participants"
    )
    health = next(write for write in plan.writes if write.collection == "health_profiles")
    line = next(write for write in plan.writes if write.collection == "booking_line_items")

    assert plan.counts == {
        "booking_line_items": 1,
        "booking_participants": 1,
        "bookings": 1,
        "health_profiles": 1,
    }
    assert booking.data["publicBookingId"].startswith("BK-TST-20260802-")
    assert booking.data["customerName"].startswith("Test Guest ")
    assert booking.data["contact"] == {"mode": "NONE"}
    assert booking.data["status"] == "RECORDED"
    assert booking.data["financiallyExcluded"] is True
    assert booking.data["paymentStatus"] == "UNAVAILABLE"
    assert participant.data["nickname"].startswith("Test Guest ")
    assert participant.data["healthAlert"] is False
    assert health.data["hasInformation"] is False
    assert health.data["details"] == ""
    assert line.data["financiallyExcluded"] is True
    assert "internalNote" not in line.data["serviceSnapshot"]
    assert not FORBIDDEN_KEYS.intersection(
        key for write in plan.writes for key in walk_keys(write.data)
    )
    assert {write.collection for write in plan.writes}.isdisjoint(
        {
            "payments",
            "payment_attempts",
            "accounting_exports",
            "consent_evidence",
            "audit_events",
            "notification_outbox",
            "capacity_buckets",
            "line_booking_links",
        }
    )


def test_plan_is_deterministic_and_references_are_remapped() -> None:
    first = make_plan()
    second = make_plan()
    participant = next(
        write for write in first.writes if write.collection == "booking_participants"
    )
    health = next(write for write in first.writes if write.collection == "health_profiles")
    line = next(write for write in first.writes if write.collection == "booking_line_items")

    assert plan_digest(first) == plan_digest(second)
    assert participant.document_id == line.data["participantIds"][0]
    assert participant.data["healthProfileId"] == health.document_id
    assert len({write.path for write in first.writes}) == len(first.writes)


def test_plan_rejects_incomplete_relations() -> None:
    bookings, lines, _ = source_documents()
    with pytest.raises(ValueError, match="no participants"):
        build_plan(
            bookings,
            lines,
            [],
            from_date=FROM_DATE,
            to_date=TO_DATE,
            run_id=RUN_ID,
        )


def test_apply_requires_exact_target_and_reviewed_digest() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--from-date",
                "2026-08-02",
                "--to-date",
                "2026-09-01",
                "--apply",
                "--confirm-target",
                "spa-db",
                "--confirm-plan",
                "digest",
            ]
        )
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--from-date",
                "2026-08-02",
                "--to-date",
                "2026-09-01",
                "--apply",
                "--confirm-target",
                "spa-test-db",
            ]
        )


def test_today_or_future_dates_are_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--from-date",
                date.today().isoformat(),
                "--to-date",
                date.today().isoformat(),
            ]
        )
