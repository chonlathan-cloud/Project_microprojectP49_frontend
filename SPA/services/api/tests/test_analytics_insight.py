from app.domains.analytics.insight import InsightFilters, build_insight_payload


def test_insight_filters_and_summarizes_without_double_counting_package_revenue() -> None:
    bookings = {
        "booking-1": {
            "publicBookingId": "BK-001",
            "status": "COMPLETED",
            "source": "ADMIN_WEB",
            "adminEntryMode": "WALK_IN",
            "localDate": "2026-09-02",
            "localStartTime": "14:00",
            "pax": 2,
            "subtotalAmountSatang": 100_000,
            "discountAmountSatang": 10_000,
            "estimatedAmountSatang": 90_000,
            "tipAmountSatang": 10_000,
            "grossAmountSatang": 100_000,
            "paymentStatus": "PAID",
            "paidAmountSatang": 100_000,
        },
        "booking-2": {
            "publicBookingId": "BK-002",
            "status": "RECORDED",
            "source": "ADMIN_WEB",
            "adminEntryMode": "HISTORICAL_RECORD",
            "localDate": "2026-09-01",
            "localStartTime": "10:00",
            "pax": 1,
            "subtotalAmountSatang": 60_000,
            "estimatedAmountSatang": 60_000,
            "tipAmountSatang": 0,
            "grossAmountSatang": 60_000,
        },
    }
    lines = [
        {
            "bookingDocId": "booking-1",
            "lineTotalSatang": 100_000,
            "participantIds": ["p1", "p2"],
            "serviceSnapshot": {
                "serviceId": "couple",
                "variantId": "couple-120",
                "nameTh": "แพ็กเกจคู่",
                "nameEn": "Couple package",
                "durationMinutes": 120,
            },
        },
        {
            "bookingDocId": "booking-2",
            "lineTotalSatang": 60_000,
            "participantIds": ["p3"],
            "serviceSnapshot": {
                "serviceId": "thai",
                "variantId": "thai-120",
                "nameTh": "นวดแผนไทย",
                "nameEn": "Thai massage",
                "durationMinutes": 120,
            },
        },
    ]
    settlements = {
        "booking-1": {
            "sourceTipAmountSatang": 10_000,
            "therapistPaySatang": 60_000,
            "therapistTipSatang": 8_000,
            "shopTotalSatang": 32_000,
            "allocations": [
                {
                    "therapistId": "therapist-1",
                    "therapistName": "หนึ่ง",
                    "durationMinutes": 120,
                    "therapistPaySatang": 30_000,
                    "tipShareSatang": 4_000,
                },
                {
                    "therapistId": "therapist-2",
                    "therapistName": "สอง",
                    "durationMinutes": 120,
                    "therapistPaySatang": 30_000,
                    "tipShareSatang": 4_000,
                },
            ],
        }
    }

    bookings_result = build_insight_payload(
        bookings=bookings,
        lines=lines,
        settlements=settlements,
        filters=InsightFilters(admin_entry_mode="WALK_IN"),
        view="BOOKINGS",
        page=1,
        page_size=50,
    )
    assert bookings_result["summary"]["grossAmountSatang"] == 100_000
    assert bookings_result["summary"]["bookingCount"] == 1
    assert set(bookings_result["items"][0]["therapistNames"]) == {"หนึ่ง", "สอง"}

    services_result = build_insight_payload(
        bookings=bookings,
        lines=lines,
        settlements=settlements,
        filters=InsightFilters(service_id="couple"),
        view="SERVICES",
        page=1,
        page_size=50,
    )
    assert services_result["items"][0]["sessionCount"] == 1
    assert services_result["items"][0]["participantCount"] == 2
    assert services_result["items"][0]["netServiceSatang"] == 90_000


def test_insight_excludes_stale_settlement_totals_and_supports_pagination() -> None:
    bookings = {
        f"booking-{index}": {
            "publicBookingId": f"BK-{index}",
            "status": "COMPLETED",
            "localDate": "2026-09-02",
            "localStartTime": f"{10 + index}:00",
            "estimatedAmountSatang": 50_000,
            "tipAmountSatang": 5_000,
            "grossAmountSatang": 55_000,
        }
        for index in range(3)
    }
    settlements = {
        "booking-0": {
            "sourceTipAmountSatang": 0,
            "therapistPaySatang": 30_000,
            "shopTotalSatang": 25_000,
        }
    }
    result = build_insight_payload(
        bookings=bookings,
        lines=[],
        settlements=settlements,
        filters=InsightFilters(),
        view="BOOKINGS",
        page=2,
        page_size=2,
    )
    assert result["summary"]["settlementPendingCount"] == 3
    assert result["summary"]["therapistPaySatang"] == 0
    assert result["pagination"] == {
        "page": 2,
        "pageSize": 2,
        "totalItems": 3,
        "totalPages": 2,
    }
    assert len(result["items"]) == 1
