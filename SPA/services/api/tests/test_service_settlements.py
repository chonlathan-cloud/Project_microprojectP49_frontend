from fastapi.testclient import TestClient

from app.api.v1.analytics import _allocate_discount
from app.core.auth import require_admin_user
from app.core.errors import ValidationDomainError
from app.domains.settlements.service import (
    SettlementAllocation,
    calculate_settlement_totals,
)
from app.infrastructure.firestore import get_firestore_client
from app.main import app


def test_shop_absorbs_discount_without_reducing_therapist_pay() -> None:
    totals = calculate_settlement_totals(
        net_service_amount_satang=55_000,
        source_tip_amount_satang=0,
        allocations=(
            SettlementAllocation(
                participant_id="participant-1",
                therapist_id="therapist-1",
                therapist_pay_satang=40_000,
                tip_share_satang=0,
            ),
        ),
    )

    assert totals.therapist_pay_satang == 40_000
    assert totals.shop_service_amount_satang == 15_000
    assert totals.shop_total_satang == 15_000


def test_tip_can_be_split_between_multiple_therapists_and_shop() -> None:
    totals = calculate_settlement_totals(
        net_service_amount_satang=60_000,
        source_tip_amount_satang=10_000,
        allocations=(
            SettlementAllocation("participant-1", "therapist-1", 20_000, 6_000),
            SettlementAllocation("participant-2", "therapist-2", 15_000, 2_000),
        ),
    )

    assert totals.therapist_tip_satang == 8_000
    assert totals.shop_tip_satang == 2_000
    assert totals.shop_service_amount_satang == 25_000
    assert totals.shop_total_satang == 27_000


def test_store_loss_is_allowed_and_explicit() -> None:
    totals = calculate_settlement_totals(
        net_service_amount_satang=30_000,
        source_tip_amount_satang=0,
        allocations=(SettlementAllocation("participant-1", "therapist-1", 40_000, 0),),
    )

    assert totals.shop_service_amount_satang == -10_000
    assert totals.negative_shop_service_amount is True


def test_pay_requires_a_therapist() -> None:
    try:
        calculate_settlement_totals(
            net_service_amount_satang=60_000,
            source_tip_amount_satang=0,
            allocations=(SettlementAllocation("participant-1", None, 40_000, 0),),
        )
    except ValidationDomainError as error:
        assert "therapist is required" in error.detail.lower()
    else:
        raise AssertionError("Expected therapist validation to fail")


def test_booking_discount_is_allocated_deterministically_across_services() -> None:
    groups = [
        (("service-a", "a-60"), {"grossServiceSatang": 40_000}),
        (("service-b", "b-60"), {"grossServiceSatang": 60_000}),
    ]

    assert _allocate_discount(groups, 10_000) == {
        ("service-a", "a-60"): 4_000,
        ("service-b", "b-60"): 6_000,
    }


def test_staff_cannot_read_financial_settlement_or_analytics() -> None:
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "staff-001",
        "role": "STAFF",
    }
    app.dependency_overrides[get_firestore_client] = object
    client = TestClient(app)
    try:
        settlement = client.get("/api/v1/admin/bookings/BK-001/settlement")
        analytics = client.get(
            "/api/v1/admin/analytics/overview",
            params={"dateFrom": "2026-09-01", "dateTo": "2026-09-02"},
        )
        insight = client.get(
            "/api/v1/admin/analytics/insight",
            params={"dateFrom": "2026-09-01", "dateTo": "2026-09-02"},
        )
        insight_export = client.post(
            "/api/v1/admin/analytics/insight:export",
            json={"dateFrom": "2026-09-01", "dateTo": "2026-09-02"},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert settlement.status_code == 403
    assert analytics.status_code == 403
    assert insight.status_code == 403
    assert insight_export.status_code == 403
