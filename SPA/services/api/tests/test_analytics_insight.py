import csv
import io

from fastapi.testclient import TestClient

from app.api.v1 import analytics as analytics_api
from app.api.v1.analytics import SALES_CSV_FIELDS, _sales_csv_row
from app.core.auth import require_admin_user
from app.domains.analytics.insight import InsightFilters, build_insight_payload
from app.infrastructure.firestore import get_firestore_client
from app.main import app


class _AuditDocument:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = events

    def set(self, payload: dict[str, object]) -> None:
        self.events.append(payload)


class _AuditCollection:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = events

    def document(self) -> _AuditDocument:
        return _AuditDocument(self.events)


class _AuditClient:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def collection(self, name: str) -> _AuditCollection:
        assert name == "audit_events"
        return _AuditCollection(self.events)


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
            "version": 5,
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
            "sourceBookingVersion": 5,
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
    assert bookings_result["items"][0]["durationMinutes"] == 120

    export_row = _sales_csv_row(bookings_result["items"][0])
    assert tuple(export_row) == SALES_CSV_FIELDS
    assert export_row["ราคาขายสุทธิ (บาท)"] == "900.00"
    assert export_row["ค่ามือหมอ (บาท)"] == "600.00"
    assert export_row["เงินร้านจากค่าบริการ (บาท)"] == "300.00"
    assert export_row["ทิปรวม (บาท)"] == "100.00"
    assert export_row["ทิปหมอ (บาท)"] == "80.00"
    assert export_row["ทิปร้าน (บาท)"] == "20.00"
    assert export_row["สถานะชำระเงิน"] == "จ่ายแล้ว"
    assert export_row["สถานะสรุปค่าหมอ"] == "สรุปแล้ว"

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


def test_insight_marks_settlement_stale_after_booking_discount_version_changes() -> None:
    result = build_insight_payload(
        bookings={
            "booking-1": {
                "publicBookingId": "BK-001",
                "status": "COMPLETED",
                "version": 6,
                "localDate": "2026-09-02",
                "localStartTime": "14:00",
                "discountAmountSatang": 5_000,
                "estimatedAmountSatang": 45_000,
                "tipAmountSatang": 0,
                "grossAmountSatang": 45_000,
            }
        },
        lines=[],
        settlements={
            "booking-1": {
                "sourceBookingVersion": 5,
                "discountAmountSatang": 0,
                "netServiceAmountSatang": 50_000,
                "sourceTipAmountSatang": 0,
                "therapistPaySatang": 30_000,
                "shopTotalSatang": 20_000,
            }
        },
        filters=InsightFilters(),
        view="BOOKINGS",
        page=1,
        page_size=50,
    )

    assert result["items"][0]["settlementState"] == "STALE"
    assert result["summary"]["therapistPaySatang"] == 0
    export_row = _sales_csv_row(result["items"][0])
    assert export_row["ค่ามือหมอ (บาท)"] == ""
    assert export_row["เงินร้านจากค่าบริการ (บาท)"] == ""
    assert export_row["ทิปหมอ (บาท)"] == ""
    assert export_row["ทิปร้าน (บาท)"] == ""
    assert export_row["สถานะสรุปค่าหมอ"] == "ต้องตรวจใหม่"


def test_sales_csv_export_has_thai_filename_bom_safe_cells_and_audit(
    monkeypatch,
) -> None:
    audit_client = _AuditClient()
    monkeypatch.setattr(
        analytics_api,
        "_load_insight_payload",
        lambda **_kwargs: {
            "items": [
                {
                    "localDate": "2026-10-08",
                    "localStartTime": "10:30",
                    "durationMinutes": 90,
                    "bookingId": "=unsafe-booking-id",
                    "serviceNamesTh": ["นวดไทย"],
                    "therapistNames": ["คุณนิด"],
                    "netServiceAmountSatang": 45_000,
                    "therapistPaySatang": 25_000,
                    "tipAmountSatang": 5_000,
                    "therapistTipSatang": 5_000,
                    "paymentStatus": "PAID",
                    "settlementState": "ALLOCATED",
                }
            ]
        },
    )
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "admin-001",
        "role": "ADMIN",
    }
    app.dependency_overrides[get_firestore_client] = lambda: audit_client
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/admin/analytics/insight:export",
            json={
                "dateFrom": "2026-10-01",
                "dateTo": "2026-10-31",
                "view": "BOOKINGS",
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == SALES_CSV_FIELDS
    assert rows[0]["เลขที่รายการ"] == "'=unsafe-booking-id"
    assert rows[0]["เงินร้านจากค่าบริการ (บาท)"] == "200.00"
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert (
        "%E0%B8%A3%E0%B8%B2%E0%B8%A2%E0%B8%81%E0%B8%B2%E0%B8%A3"
        "%E0%B8%82%E0%B8%B2%E0%B8%A2"
    ) in disposition
    assert audit_client.events[0]["eventType"] == "ANALYTICS_CSV_EXPORTED"
    assert audit_client.events[0]["recordCount"] == 1
