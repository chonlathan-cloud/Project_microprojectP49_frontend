import csv
import io
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.v1 import compensation as compensation_api
from app.api.v1.analytics import _payout_covers_service_date
from app.api.v1.compensation import (
    DAILY_COMPENSATION_CSV_FIELDS,
    SUMMARY_COMPENSATION_CSV_FIELDS,
    _build_compensation_payload,
    _compensation_export_rows,
)
from app.core.auth import require_admin_user
from app.domains.compensation.service import calculate_daily_compensation
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


def test_daily_guarantee_uses_service_pay_but_not_tip() -> None:
    result = calculate_daily_compensation(
        present=True,
        service_pay_satang=25_000,
        tip_satang=10_000,
        guarantee_rate_satang=40_000,
    )

    assert result.guarantee_top_up_satang == 15_000
    assert result.total_earned_satang == 50_000


def test_absent_therapist_does_not_receive_guarantee() -> None:
    result = calculate_daily_compensation(
        present=False,
        service_pay_satang=0,
        tip_satang=0,
        guarantee_rate_satang=40_000,
    )

    assert result.guarantee_top_up_satang == 0
    assert result.total_earned_satang == 0


def test_compensation_payload_separates_service_shop_tip_and_payout() -> None:
    payload = _build_compensation_payload(
        therapists=[
            {
                "documentId": "therapist-1",
                "therapistId": "therapist-1",
                "displayName": "คุณนิด",
                "branchId": "branch_001",
                "active": True,
                "version": 2,
            }
        ],
        guarantee_rates=[
            {
                "therapistId": "therapist-1",
                "effectiveFrom": "2026-09-01",
                "dailyGuaranteeSatang": 40_000,
            }
        ],
        attendances=[
            {
                "documentId": "attendance-1",
                "therapistId": "therapist-1",
                "localDate": "2026-09-03",
                "present": True,
                "guaranteeRateSatang": 40_000,
                "version": 1,
            }
        ],
        settlements=[
            {
                "documentId": "booking-doc-1",
                "bookingPublicId": "BK-001",
                "serviceDate": "2026-09-03",
                "allocations": [
                    {
                        "bookingLineItemId": "line-1",
                        "therapistId": "therapist-1",
                        "therapistPaySatang": 25_000,
                        "tipShareSatang": 5_000,
                        "durationMinutes": 60,
                        "serviceNameTh": "นวดเท้า",
                    }
                ],
                "version": 1,
            }
        ],
        adjustments=[
            {
                "documentId": "adjustment-1",
                "therapistId": "therapist-1",
                "localDate": "2026-09-03",
                "kind": "BONUS",
                "amountSatang": 2_000,
                "reason": "งานพิเศษ",
                "version": 1,
            }
        ],
        payouts=[
            {
                "documentId": "payout-1",
                "therapistId": "therapist-1",
                "dateFrom": "2026-09-03",
                "dateTo": "2026-09-03",
                "amountSatang": 20_000,
                "paymentMethod": "CASH",
            }
        ],
        start=date(2026, 9, 3),
        end=date(2026, 9, 3),
        branch_id="branch_001",
    )

    row = payload["summary"][0]
    assert row["servicePaySatang"] == 25_000
    assert row["guaranteeTopUpSatang"] == 15_000
    assert row["shopAdjustmentSatang"] == 2_000
    assert row["tipSatang"] == 5_000
    assert row["totalEarnedSatang"] == 47_000
    assert row["paidSatang"] == 20_000
    assert row["outstandingSatang"] == 27_000
    assert {item["source"] for item in payload["entries"]} == {"SERVICE", "SHOP"}
    assert all(item["editable"] is False for item in payload["entries"])

    daily_fields, daily_rows = _compensation_export_rows(payload, "DAILY_DETAIL")
    assert daily_fields == DAILY_COMPENSATION_CSV_FIELDS
    assert daily_rows == [
        {
            "วันที่": "2026-09-03",
            "ชื่อหมอนวด": "คุณนิด",
            "สถานะมาทำงาน": "มาทำงาน",
            "จำนวนงาน": 1,
            "เวลานวดรวม (นาที)": 60,
            "ค่ามือจากบริการ (บาท)": "250.00",
            "ค่าประกันมือต่อวัน (บาท)": "400.00",
            "เงินเติมค่าประกันจากร้าน (บาท)": "150.00",
            "โบนัส/รายการปรับปรุงจากร้าน (บาท)": "20.00",
            "ทิปหมอ (บาท)": "50.00",
            "รายได้หมอรวมของวัน (บาท)": "470.00",
            "จ่ายแล้ว (บาท)": "200.00",
            "ค้างจ่าย (บาท)": "270.00",
        }
    ]

    summary_fields, summary_rows = _compensation_export_rows(
        payload, "THERAPIST_SUMMARY"
    )
    assert summary_fields == SUMMARY_COMPENSATION_CSV_FIELDS
    assert summary_rows[0]["ชื่อหมอนวด"] == "คุณนิด"
    assert summary_rows[0]["รวมรายได้หมอ (บาท)"] == "470.00"
    assert summary_rows[0]["ค้างจ่าย (บาท)"] == "270.00"
    assert summary_rows[0]["สถานะการจ่าย"] == "จ่ายบางส่วน"


def test_voided_settlement_is_excluded_from_compensation() -> None:
    payload = _build_compensation_payload(
        therapists=[
            {
                "documentId": "therapist-1",
                "therapistId": "therapist-1",
                "displayName": "คุณนิด",
                "branchId": "branch_001",
                "active": True,
            }
        ],
        guarantee_rates=[],
        attendances=[],
        settlements=[
            {
                "documentId": "booking-doc-1",
                "bookingPublicId": "BK-VOIDED",
                "serviceDate": "2026-09-03",
                "state": "VOIDED",
                "allocations": [
                    {
                        "bookingLineItemId": "line-1",
                        "therapistId": "therapist-1",
                        "therapistPaySatang": 25_000,
                        "tipShareSatang": 5_000,
                    }
                ],
            }
        ],
        adjustments=[],
        payouts=[],
        start=date(2026, 9, 3),
        end=date(2026, 9, 3),
        branch_id="branch_001",
    )

    row = payload["summary"][0]
    assert row["servicePaySatang"] == 0
    assert row["tipSatang"] == 0
    assert row["outstandingSatang"] == 0
    assert payload["entries"] == []


def test_staff_cannot_access_compensation_financials() -> None:
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "staff-001",
        "role": "STAFF",
    }
    app.dependency_overrides[get_firestore_client] = object
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/admin/therapist-compensation",
            params={"dateFrom": "2026-09-03", "dateTo": "2026-09-03"},
        )
        export_response = client.post(
            "/api/v1/admin/therapist-compensation:export",
            json={
                "dateFrom": "2026-09-03",
                "dateTo": "2026-09-03",
                "reportType": "DAILY_DETAIL",
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 403
    assert export_response.status_code == 403


def test_compensation_csv_export_has_thai_filename_bom_and_audit(monkeypatch) -> None:
    audit_client = _AuditClient()
    monkeypatch.setattr(
        compensation_api,
        "_load_payload",
        lambda *_args, **_kwargs: {
            "summary": [
                {
                    "therapistId": "therapist-1",
                    "therapistName": "คุณนิด",
                    "attendedDays": 1,
                    "serviceCount": 0,
                    "durationMinutes": 0,
                    "servicePaySatang": 0,
                    "guaranteeTopUpSatang": 40_000,
                    "shopAdjustmentSatang": 0,
                    "tipSatang": 0,
                    "totalEarnedSatang": 40_000,
                    "paidSatang": 0,
                    "outstandingSatang": 40_000,
                    "payoutState": "UNPAID",
                    "days": [
                        {
                            "localDate": "2026-10-08",
                            "present": True,
                            "serviceCount": 0,
                            "durationMinutes": 0,
                            "servicePaySatang": 0,
                            "guaranteeRateSatang": 40_000,
                            "guaranteeTopUpSatang": 40_000,
                            "shopAdjustmentSatang": 0,
                            "tipSatang": 0,
                            "totalEarnedSatang": 40_000,
                            "paidSatang": 0,
                            "outstandingSatang": 40_000,
                        }
                    ],
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
            "/api/v1/admin/therapist-compensation:export",
            json={
                "dateFrom": "2026-10-01",
                "dateTo": "2026-10-31",
                "reportType": "DAILY_DETAIL",
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == DAILY_COMPENSATION_CSV_FIELDS
    assert rows[0]["จำนวนงาน"] == "0"
    assert rows[0]["เงินเติมค่าประกันจากร้าน (บาท)"] == "400.00"
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert (
        "%E0%B8%84%E0%B9%88%E0%B8%B2%E0%B8%95%E0%B8%AD%E0%B8%9A"
        "%E0%B9%81%E0%B8%97%E0%B8%99"
    ) in disposition
    assert audit_client.events[0]["eventType"] == "THERAPIST_COMPENSATION_CSV_EXPORTED"
    assert audit_client.events[0]["recordCount"] == 1


def test_compensation_range_is_bounded() -> None:
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "admin-001",
        "role": "ADMIN",
    }
    app.dependency_overrides[get_firestore_client] = object
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/admin/therapist-compensation",
            params={"dateFrom": "2026-01-01", "dateTo": "2026-09-03"},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 422
    assert "93 days" in response.json()["detail"]


def test_effective_dated_guarantee_uses_rate_for_each_day() -> None:
    payload = _build_compensation_payload(
        therapists=[
            {
                "documentId": "therapist-1",
                "displayName": "คุณนิด",
                "active": True,
            }
        ],
        guarantee_rates=[
            {
                "therapistId": "therapist-1",
                "effectiveFrom": "2026-09-01",
                "dailyGuaranteeSatang": 40_000,
            },
            {
                "therapistId": "therapist-1",
                "effectiveFrom": "2026-09-02",
                "dailyGuaranteeSatang": 45_000,
            },
        ],
        attendances=[
            {
                "therapistId": "therapist-1",
                "localDate": "2026-09-01",
                "present": True,
                "version": 1,
            },
            {
                "therapistId": "therapist-1",
                "localDate": "2026-09-02",
                "present": True,
                "version": 1,
            },
        ],
        settlements=[],
        adjustments=[],
        payouts=[],
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        branch_id="branch_001",
    )

    row = payload["summary"][0]
    assert row["guaranteeTopUpSatang"] == 85_000
    assert [item["guaranteeRateSatang"] for item in row["days"]] == [
        40_000,
        45_000,
    ]


def test_daily_payout_allocation_prevents_duplicate_payment_for_subrange() -> None:
    payload = _build_compensation_payload(
        therapists=[
            {
                "documentId": "therapist-1",
                "displayName": "คุณนิด",
                "active": True,
            }
        ],
        guarantee_rates=[],
        attendances=[],
        settlements=[
            {
                "documentId": "booking-doc-1",
                "serviceDate": "2026-09-02",
                "allocations": [
                    {
                        "bookingLineItemId": "line-1",
                        "therapistId": "therapist-1",
                        "therapistPaySatang": 50_000,
                        "tipShareSatang": 0,
                    }
                ],
            }
        ],
        adjustments=[],
        payouts=[
            {
                "documentId": "payout-1",
                "therapistId": "therapist-1",
                "dateFrom": "2026-09-01",
                "dateTo": "2026-09-03",
                "amountSatang": 50_000,
                "dailyAllocations": [
                    {"localDate": "2026-09-02", "amountSatang": 50_000}
                ],
            }
        ],
        start=date(2026, 9, 2),
        end=date(2026, 9, 2),
        branch_id="branch_001",
    )

    row = payload["summary"][0]
    assert row["paidSatang"] == 50_000
    assert row["outstandingSatang"] == 0
    assert row["payoutState"] == "PAID"


def test_adjustment_created_after_payout_remains_editable() -> None:
    paid_at = datetime(2026, 9, 3, 10, tzinfo=UTC)
    payload = _build_compensation_payload(
        therapists=[
            {
                "documentId": "therapist-1",
                "displayName": "คุณนิด",
                "active": True,
            }
        ],
        guarantee_rates=[],
        attendances=[
            {
                "therapistId": "therapist-1",
                "localDate": "2026-09-03",
                "present": True,
                "guaranteeRateSatang": 40_000,
                "version": 1,
            }
        ],
        settlements=[],
        adjustments=[
            {
                "documentId": "adjustment-after-payout",
                "therapistId": "therapist-1",
                "localDate": "2026-09-03",
                "kind": "ADJUSTMENT",
                "amountSatang": 1_000,
                "reason": "แก้ยอดหลังจ่าย",
                "createdAt": paid_at + timedelta(minutes=5),
            }
        ],
        payouts=[
            {
                "documentId": "payout-1",
                "therapistId": "therapist-1",
                "dateFrom": "2026-09-03",
                "dateTo": "2026-09-03",
                "amountSatang": 40_000,
                "dailyAllocations": [
                    {"localDate": "2026-09-03", "amountSatang": 40_000}
                ],
                "paidAt": paid_at,
            }
        ],
        start=date(2026, 9, 3),
        end=date(2026, 9, 3),
        branch_id="branch_001",
    )

    entry = next(
        item
        for item in payload["entries"]
        if item["entryId"] == "adjustment-after-payout"
    )
    assert entry["editable"] is True
    assert payload["summary"][0]["outstandingSatang"] == 1_000


def test_settlement_lock_uses_daily_payout_allocation() -> None:
    payout = {
        "therapistId": "therapist-1",
        "dateFrom": "2026-09-01",
        "dateTo": "2026-09-03",
        "dailyAllocations": [
            {"localDate": "2026-09-02", "amountSatang": 50_000}
        ],
    }

    assert _payout_covers_service_date(
        payout,
        therapist_ids={"therapist-1"},
        service_date="2026-09-02",
    )
    assert not _payout_covers_service_date(
        payout,
        therapist_ids={"therapist-1"},
        service_date="2026-09-01",
    )
