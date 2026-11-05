from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.auth import require_admin_user
from app.core.errors import (
    ConflictDomainError,
    NotFoundDomainError,
    ValidationDomainError,
)
from app.domains.compensation.service import calculate_daily_compensation
from app.infrastructure.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1/admin", tags=["admin-compensation"])
DEFAULT_DAILY_GUARANTEE_SATANG = 40_000
MAX_RANGE_DAYS = 93


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class CompensationProfileUpdate(ApiModel):
    daily_guarantee_satang: int = Field(ge=0, multiple_of=100)
    effective_from: str
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=300)


class AttendanceUpdate(ApiModel):
    present: bool
    expected_version: int = Field(ge=0)


class AdjustmentCreate(ApiModel):
    branch_id: Literal["branch_001"] = "branch_001"
    therapist_id: str = Field(min_length=1, max_length=160)
    local_date: str
    amount_satang: int = Field(multiple_of=100)
    kind: Literal["BONUS", "ADJUSTMENT"] = "ADJUSTMENT"
    reason: str = Field(min_length=1, max_length=300)
    command_id: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_amount(self) -> AdjustmentCreate:
        if self.amount_satang == 0:
            raise ValueError("Adjustment amount cannot be zero")
        return self


class AdjustmentUpdate(ApiModel):
    amount_satang: int = Field(multiple_of=100)
    kind: Literal["BONUS", "ADJUSTMENT"]
    reason: str = Field(min_length=1, max_length=300)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_amount(self) -> AdjustmentUpdate:
        if self.amount_satang == 0:
            raise ValueError("Adjustment amount cannot be zero")
        return self


class PayoutCreate(ApiModel):
    branch_id: Literal["branch_001"] = "branch_001"
    therapist_id: str = Field(min_length=1, max_length=160)
    date_from: str
    date_to: str
    payment_method: Literal["CASH", "TRANSFER"]
    note: str = Field(default="", max_length=300)
    command_id: str = Field(min_length=8, max_length=160)


class CompensationExportInput(ApiModel):
    branch_id: Literal["branch_001"] = "branch_001"
    date_from: str
    date_to: str
    report_type: Literal["DAILY_DETAIL", "THERAPIST_SUMMARY"]
    therapist_id: str | None = Field(default=None, min_length=1, max_length=160)


def _require_admin(actor: dict[str, object]) -> None:
    if actor.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="ADMIN role is required")


def _parse_range(date_from: str, date_to: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError as error:
        raise ValidationDomainError("Compensation date range is invalid") from error
    if end < start:
        raise ValidationDomainError("Compensation end date must not precede start date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValidationDomainError(
            f"Compensation date range cannot exceed {MAX_RANGE_DAYS} days"
        )
    return start, end


def _snapshot_items(
    client: firestore.Client,
    collection_name: str,
    *,
    branch_id: str,
    transaction: firestore.Transaction | None = None,
    date_field: str | None = None,
    range_start: date | None = None,
    range_end: date | None = None,
) -> list[dict[str, object]]:
    query = client.collection(collection_name)
    if date_field:
        if range_start:
            query = query.where(date_field, ">=", range_start.isoformat())
        if range_end:
            query = query.where(date_field, "<=", range_end.isoformat())
    else:
        query = query.where("branchId", "==", branch_id)
    snapshots = list(query.stream(transaction=transaction))
    return [
        {"documentId": item.id, **data}
        for item in snapshots
        if (data := (item.to_dict() or {})).get("branchId") == branch_id
    ]


def _in_range(value: object, start: date, end: date) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return start <= parsed <= end


def _period_overlaps_range(item: dict[str, object], start: date, end: date) -> bool:
    try:
        period_start = date.fromisoformat(str(item.get("dateFrom")))
        period_end = date.fromisoformat(str(item.get("dateTo")))
    except ValueError:
        return False
    return period_start <= end and start <= period_end


def _payout_daily_allocations(
    payout: dict[str, object], start: date, end: date
) -> list[tuple[str, int]]:
    allocations = payout.get("dailyAllocations")
    if isinstance(allocations, list):
        result: list[tuple[str, int]] = []
        for allocation in allocations:
            if not isinstance(allocation, dict):
                continue
            local_date = str(allocation.get("localDate") or "")
            if _in_range(local_date, start, end):
                result.append((local_date, int(allocation.get("amountSatang", 0))))
        return result

    # A legacy payout has no reliable per-day split. Count it only when the
    # selected range contains its complete original period.
    try:
        period_start = date.fromisoformat(str(payout.get("dateFrom")))
        period_end = date.fromisoformat(str(payout.get("dateTo")))
    except ValueError:
        return []
    if start <= period_start and period_end <= end:
        return [(period_start.isoformat(), int(payout.get("amountSatang", 0)))]
    return []


def _build_compensation_payload(
    *,
    therapists: list[dict[str, object]],
    guarantee_rates: list[dict[str, object]],
    attendances: list[dict[str, object]],
    settlements: list[dict[str, object]],
    adjustments: list[dict[str, object]],
    payouts: list[dict[str, object]],
    start: date,
    end: date,
    branch_id: str,
) -> dict[str, object]:
    therapist_by_id = {
        str(item.get("therapistId") or item.get("documentId")): item
        for item in therapists
    }
    rates_by_therapist: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in guarantee_rates:
        therapist_id = str(item.get("therapistId") or "")
        effective_from = item.get("effectiveFrom")
        if therapist_id and isinstance(effective_from, str):
            rates_by_therapist[therapist_id].append(item)
    for rates in rates_by_therapist.values():
        rates.sort(key=lambda item: str(item["effectiveFrom"]))

    def guarantee_rate_for(therapist_id: str, local_date: str) -> int:
        applicable = [
            item
            for item in rates_by_therapist.get(therapist_id, [])
            if str(item["effectiveFrom"]) <= local_date
        ]
        if applicable:
            return int(applicable[-1].get("dailyGuaranteeSatang", 0))
        return DEFAULT_DAILY_GUARANTEE_SATANG
    daily: dict[tuple[str, str], dict[str, object]] = defaultdict(
        lambda: {
            "servicePaySatang": 0,
            "tipSatang": 0,
            "serviceCount": 0,
            "durationMinutes": 0,
            "shopAdjustmentSatang": 0,
            "adjustments": [],
            "serviceEntries": [],
        }
    )
    attendance_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for item in attendances:
        local_date = str(item.get("localDate") or "")
        therapist_id = str(item.get("therapistId") or "")
        if therapist_id and _in_range(local_date, start, end):
            attendance_by_key[(therapist_id, local_date)] = item

    entries: list[dict[str, object]] = []
    for settlement in settlements:
        if settlement.get("state") == "VOIDED":
            continue
        local_date = str(settlement.get("serviceDate") or "")
        if not _in_range(local_date, start, end):
            continue
        booking_id = str(
            settlement.get("bookingPublicId") or settlement.get("bookingDocId") or ""
        )
        for allocation in settlement.get("allocations") or []:
            if not isinstance(allocation, dict) or not allocation.get("therapistId"):
                continue
            therapist_id = str(allocation["therapistId"])
            if therapist_id not in therapist_by_id:
                continue
            pay = int(allocation.get("therapistPaySatang", 0))
            tip = int(allocation.get("tipShareSatang", 0))
            item = daily[(therapist_id, local_date)]
            item["servicePaySatang"] = int(item["servicePaySatang"]) + pay
            item["tipSatang"] = int(item["tipSatang"]) + tip
            item["serviceCount"] = int(item["serviceCount"]) + 1
            item["durationMinutes"] = int(item["durationMinutes"]) + int(
                allocation.get("durationMinutes", 0)
            )
            entry = {
                "entryId": (
                    f"{settlement.get('documentId')}:{allocation.get('bookingLineItemId')}"
                ),
                "source": "SERVICE",
                "kind": "SERVICE_ALLOCATION",
                "localDate": local_date,
                "therapistId": therapist_id,
                "therapistName": therapist_by_id[therapist_id].get("displayName"),
                "amountSatang": pay,
                "tipSatang": tip,
                "bookingId": booking_id,
                "bookingLineItemId": allocation.get("bookingLineItemId"),
                "serviceNameTh": allocation.get("serviceNameTh"),
                "serviceNameEn": allocation.get("serviceNameEn"),
                "durationMinutes": int(allocation.get("durationMinutes", 0)),
                "settlementVersion": int(settlement.get("version", 0)),
                "createdAt": settlement.get("updatedAt") or settlement.get("createdAt"),
                "editable": True,
            }
            entries.append(entry)
            item["serviceEntries"].append(entry)

    for adjustment in adjustments:
        local_date = str(adjustment.get("localDate") or "")
        therapist_id = str(adjustment.get("therapistId") or "")
        if therapist_id not in therapist_by_id or not _in_range(local_date, start, end):
            continue
        amount = int(adjustment.get("amountSatang", 0))
        item = daily[(therapist_id, local_date)]
        item["shopAdjustmentSatang"] = int(item["shopAdjustmentSatang"]) + amount
        entry = {
            "entryId": adjustment["documentId"],
            "source": "SHOP",
            "kind": adjustment.get("kind", "ADJUSTMENT"),
            "localDate": local_date,
            "therapistId": therapist_id,
            "therapistName": therapist_by_id[therapist_id].get("displayName"),
            "amountSatang": amount,
            "tipSatang": 0,
            "reason": adjustment.get("reason"),
            "version": int(adjustment.get("version", 1)),
            "createdAt": adjustment.get("createdAt"),
            "editable": True,
        }
        entries.append(entry)
        item["adjustments"].append(entry)

    paid_by_day: dict[tuple[str, str], int] = defaultdict(int)
    visible_payouts: list[dict[str, object]] = []
    for payout in payouts:
        if not _period_overlaps_range(payout, start, end):
            continue
        therapist_id = str(payout.get("therapistId") or "")
        if therapist_id not in therapist_by_id:
            continue
        amount = int(payout.get("amountSatang", 0))
        allocations_in_range = _payout_daily_allocations(payout, start, end)
        for local_date, allocated_amount in allocations_in_range:
            paid_by_day[(therapist_id, local_date)] += allocated_amount
        visible_payouts.append(
            {
                "payoutId": payout["documentId"],
                "therapistId": therapist_id,
                "therapistName": therapist_by_id[therapist_id].get("displayName"),
                "dateFrom": payout.get("dateFrom"),
                "dateTo": payout.get("dateTo"),
                "amountSatang": amount,
                "amountInRangeSatang": sum(
                    allocated_amount for _, allocated_amount in allocations_in_range
                ),
                "paymentMethod": payout.get("paymentMethod"),
                "note": payout.get("note"),
                "paidAt": payout.get("paidAt"),
                "paidBy": payout.get("paidBy"),
            }
        )

    # Only dates with a financial or attendance source contribute. This also
    # allows the former-staff balance view to cover old records without walking
    # every empty day since the first booking.
    dates_by_therapist: dict[str, set[str]] = defaultdict(set)
    for therapist_id, local_date in set(daily) | set(attendance_by_key) | set(paid_by_day):
        if _in_range(local_date, start, end):
            dates_by_therapist[therapist_id].add(local_date)
    summary_rows: list[dict[str, object]] = []
    for therapist_id, therapist in therapist_by_id.items():
        service_pay = 0
        tips = 0
        top_up = 0
        shop_adjustment = 0
        service_count = 0
        duration_minutes = 0
        attended_days = 0
        paid = 0
        day_rows: list[dict[str, object]] = []
        for local_date in sorted(dates_by_therapist[therapist_id]):
            raw = daily[(therapist_id, local_date)]
            attendance = attendance_by_key.get((therapist_id, local_date), {})
            present = bool(attendance.get("present", False))
            guarantee_rate = int(
                attendance.get(
                    "guaranteeRateSatang",
                    guarantee_rate_for(therapist_id, local_date),
                )
            )
            calculated = calculate_daily_compensation(
                present=present,
                service_pay_satang=int(raw["servicePaySatang"]),
                tip_satang=int(raw["tipSatang"]),
                guarantee_rate_satang=guarantee_rate,
                shop_adjustment_satang=int(raw["shopAdjustmentSatang"]),
            )
            if present:
                attended_days += 1
            service_pay += calculated.service_pay_satang
            tips += calculated.tip_satang
            top_up += calculated.guarantee_top_up_satang
            shop_adjustment += calculated.shop_adjustment_satang
            service_count += int(raw["serviceCount"])
            duration_minutes += int(raw["durationMinutes"])
            paid_for_day = paid_by_day.get((therapist_id, local_date), 0)
            paid += paid_for_day
            if (
                present
                or int(raw["serviceCount"])
                or int(raw["shopAdjustmentSatang"])
                or paid_for_day
            ):
                day_rows.append(
                    {
                        "localDate": local_date,
                        "present": present,
                        "attendanceVersion": int(attendance.get("version", 0)),
                        "guaranteeRateSatang": guarantee_rate,
                        "guaranteeTopUpSatang": calculated.guarantee_top_up_satang,
                        "serviceCount": int(raw["serviceCount"]),
                        "durationMinutes": int(raw["durationMinutes"]),
                        "servicePaySatang": calculated.service_pay_satang,
                        "tipSatang": calculated.tip_satang,
                        "shopAdjustmentSatang": calculated.shop_adjustment_satang,
                        "totalEarnedSatang": calculated.total_earned_satang,
                        "paidSatang": paid_for_day,
                        "outstandingSatang": (
                            calculated.total_earned_satang - paid_for_day
                        ),
                    }
                )
                if calculated.guarantee_top_up_satang > 0:
                    entries.append(
                        {
                            "entryId": f"guarantee:{therapist_id}:{local_date}",
                            "source": "SHOP",
                            "kind": "GUARANTEE_TOP_UP",
                            "localDate": local_date,
                            "therapistId": therapist_id,
                            "therapistName": therapist.get("displayName"),
                            "amountSatang": calculated.guarantee_top_up_satang,
                            "tipSatang": 0,
                            "reason": "Daily hand guarantee top-up",
                            "editable": False,
                        }
                    )
        total_earned = service_pay + tips + top_up + shop_adjustment
        outstanding = total_earned - paid
        payout_state = (
            "PAID"
            if total_earned > 0 and outstanding <= 0
            else "PARTIAL"
            if paid > 0
            else "UNPAID"
        )
        summary_rows.append(
            {
                "therapistId": therapist_id,
                "therapistName": therapist.get("displayName") or therapist_id,
                "active": bool(therapist.get("active", False)),
                "profileVersion": int(therapist.get("version", 1)),
                "dailyGuaranteeSatang": int(
                    guarantee_rate_for(therapist_id, end.isoformat())
                ),
                "guaranteeEffectiveFrom": therapist.get("guaranteeEffectiveFrom"),
                "attendedDays": attended_days,
                "serviceCount": service_count,
                "durationMinutes": duration_minutes,
                "servicePaySatang": service_pay,
                "tipSatang": tips,
                "guaranteeTopUpSatang": top_up,
                "shopAdjustmentSatang": shop_adjustment,
                "shopSourceSatang": top_up + shop_adjustment,
                "totalEarnedSatang": total_earned,
                "paidSatang": paid,
                "outstandingSatang": outstanding,
                "payoutState": payout_state,
                "days": day_rows,
            }
        )
    for entry in entries:
        if entry.get("editable") and _payout_locks_entry(
            payouts,
            str(entry.get("therapistId") or ""),
            str(entry.get("localDate") or ""),
            entry.get("createdAt"),
        ):
            entry["editable"] = False
            entry["lockedReason"] = "PAID"
    summary_rows.sort(key=lambda item: str(item["therapistName"]))
    entries.sort(key=lambda item: (str(item["localDate"]), str(item["entryId"])), reverse=True)
    visible_payouts.sort(key=lambda item: str(item.get("paidAt") or ""), reverse=True)
    return {
        "branchId": branch_id,
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
        "summary": summary_rows,
        "activeTotals": _compensation_totals([row for row in summary_rows if row["active"]]),
        "entries": entries,
        "payouts": visible_payouts,
        "totals": {
            "servicePaySatang": sum(int(item["servicePaySatang"]) for item in summary_rows),
            "shopSourceSatang": sum(int(item["shopSourceSatang"]) for item in summary_rows),
            "tipSatang": sum(int(item["tipSatang"]) for item in summary_rows),
            "totalEarnedSatang": sum(int(item["totalEarnedSatang"]) for item in summary_rows),
            "paidSatang": sum(int(item["paidSatang"]) for item in summary_rows),
            "outstandingSatang": sum(int(item["outstandingSatang"]) for item in summary_rows),
        },
    }


def _compensation_totals(rows: list[dict[str, object]]) -> dict[str, int]:
    return {
        field: sum(int(row[field]) for row in rows)
        for field in (
            "servicePaySatang",
            "shopSourceSatang",
            "tipSatang",
            "totalEarnedSatang",
            "paidSatang",
            "outstandingSatang",
        )
    }


def _former_outstanding_payload(client: firestore.Client, branch_id: str) -> dict[str, object]:
    therapists = [
        item
        for item in _snapshot_items(client, "therapists", branch_id=branch_id)
        if not item.get("active")
    ]
    if not therapists:
        return {"items": []}
    # Batch collection reads rather than one query per former therapist. Payout
    # records remain the authority, including legacy payments without day splits.
    sources = {
        key: _snapshot_items(client, collection, branch_id=branch_id)
        for key, collection in (
            ("guarantee_rates", "therapist_guarantee_rates"),
            ("attendances", "therapist_attendance"),
            ("settlements", "service_settlements"),
            ("adjustments", "therapist_compensation_adjustments"),
            ("payouts", "therapist_payouts"),
        )
    }
    dates = [
        str(item[field])
        for records in sources.values()
        for item in records
        for field in ("localDate", "serviceDate", "dateFrom", "dateTo")
        if item.get(field)
    ]
    if not dates:
        return {"items": []}
    payload = _build_compensation_payload(
        therapists=therapists,
        **sources,
        start=date.fromisoformat(min(dates)),
        end=date.fromisoformat(max(dates)),
        branch_id=branch_id,
    )
    items = []
    for row in payload["summary"]:
        if int(row["outstandingSatang"]) == 0:
            continue
        activity_dates = [day["localDate"] for day in row["days"]]
        activity_dates.extend(
            str(payout[field])
            for payout in sources["payouts"]
            if payout.get("therapistId") == row["therapistId"]
            for field in ("dateFrom", "dateTo")
            if payout.get(field)
        )
        items.append({**row, "dateFrom": min(activity_dates), "dateTo": max(activity_dates)})
    return {"items": items}


def _load_payload(
    client: firestore.Client,
    *,
    branch_id: str,
    start: date,
    end: date,
    transaction: firestore.Transaction | None = None,
) -> dict[str, object]:
    return _build_compensation_payload(
        therapists=_snapshot_items(
            client, "therapists", branch_id=branch_id, transaction=transaction
        ),
        guarantee_rates=_snapshot_items(
            client,
            "therapist_guarantee_rates",
            branch_id=branch_id,
            transaction=transaction,
            date_field="effectiveFrom",
            range_end=end,
        ),
        attendances=_snapshot_items(
            client,
            "therapist_attendance",
            branch_id=branch_id,
            transaction=transaction,
            date_field="localDate",
            range_start=start,
            range_end=end,
        ),
        settlements=_snapshot_items(
            client,
            "service_settlements",
            branch_id=branch_id,
            transaction=transaction,
            date_field="serviceDate",
            range_start=start,
            range_end=end,
        ),
        adjustments=_snapshot_items(
            client,
            "therapist_compensation_adjustments",
            branch_id=branch_id,
            transaction=transaction,
            date_field="localDate",
            range_start=start,
            range_end=end,
        ),
        payouts=_snapshot_items(
            client,
            "therapist_payouts",
            branch_id=branch_id,
            transaction=transaction,
            date_field="dateTo",
            range_start=start,
        ),
        start=start,
        end=end,
        branch_id=branch_id,
    )


DAILY_COMPENSATION_CSV_FIELDS = (
    "วันที่",
    "ชื่อหมอนวด",
    "สถานะมาทำงาน",
    "จำนวนงาน",
    "เวลานวดรวม (นาที)",
    "ค่ามือจากบริการ (บาท)",
    "ค่าประกันมือต่อวัน (บาท)",
    "เงินเติมค่าประกันจากร้าน (บาท)",
    "โบนัส/รายการปรับปรุงจากร้าน (บาท)",
    "ทิปหมอ (บาท)",
    "รายได้หมอรวมของวัน (บาท)",
    "จ่ายแล้ว (บาท)",
    "ค้างจ่าย (บาท)",
)

SUMMARY_COMPENSATION_CSV_FIELDS = (
    "ชื่อหมอนวด",
    "จำนวนวันที่มาทำงาน",
    "จำนวนงาน",
    "เวลานวดรวม (นาที)",
    "ค่ามือจากบริการ (บาท)",
    "เงินเติมค่าประกันจากร้าน (บาท)",
    "โบนัส/รายการปรับปรุง (บาท)",
    "ทิปหมอ (บาท)",
    "รวมรายได้หมอ (บาท)",
    "จ่ายแล้ว (บาท)",
    "ค้างจ่าย (บาท)",
    "สถานะการจ่าย",
)

PAYOUT_STATUS_TH = {
    "PAID": "จ่ายแล้ว",
    "PARTIAL": "จ่ายบางส่วน",
    "UNPAID": "ยังไม่จ่าย",
}


def _baht_csv(value: object) -> str:
    return format(Decimal(int(value or 0)) / Decimal(100), ".2f")


def _spreadsheet_safe(value: object) -> str:
    text = str(value or "")
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _compensation_export_rows(
    payload: dict[str, object],
    report_type: Literal["DAILY_DETAIL", "THERAPIST_SUMMARY"],
    therapist_id: str | None = None,
) -> tuple[tuple[str, ...], list[dict[str, object]]]:
    summary = [item for item in payload.get("summary", []) if isinstance(item, dict)]
    if therapist_id:
        summary = [item for item in summary if item.get("therapistId") == therapist_id]
        if not summary:
            raise NotFoundDomainError("Therapist not found")

    if report_type == "DAILY_DETAIL":
        rows: list[dict[str, object]] = []
        for therapist in summary:
            therapist_name = _spreadsheet_safe(therapist.get("therapistName"))
            for day in therapist.get("days", []):
                if not isinstance(day, dict):
                    continue
                rows.append(
                    {
                        "วันที่": _spreadsheet_safe(day.get("localDate")),
                        "ชื่อหมอนวด": therapist_name,
                        "สถานะมาทำงาน": "มาทำงาน" if day.get("present") else "ไม่ได้มาทำงาน",
                        "จำนวนงาน": int(day.get("serviceCount", 0)),
                        "เวลานวดรวม (นาที)": int(day.get("durationMinutes", 0)),
                        "ค่ามือจากบริการ (บาท)": _baht_csv(day.get("servicePaySatang")),
                        "ค่าประกันมือต่อวัน (บาท)": _baht_csv(
                            day.get("guaranteeRateSatang")
                        ),
                        "เงินเติมค่าประกันจากร้าน (บาท)": _baht_csv(
                            day.get("guaranteeTopUpSatang")
                        ),
                        "โบนัส/รายการปรับปรุงจากร้าน (บาท)": _baht_csv(
                            day.get("shopAdjustmentSatang")
                        ),
                        "ทิปหมอ (บาท)": _baht_csv(day.get("tipSatang")),
                        "รายได้หมอรวมของวัน (บาท)": _baht_csv(
                            day.get("totalEarnedSatang")
                        ),
                        "จ่ายแล้ว (บาท)": _baht_csv(day.get("paidSatang")),
                        "ค้างจ่าย (บาท)": _baht_csv(day.get("outstandingSatang")),
                    }
                )
        rows.sort(key=lambda item: (str(item["วันที่"]), str(item["ชื่อหมอนวด"])))
        return DAILY_COMPENSATION_CSV_FIELDS, rows

    rows = []
    for therapist in summary:
        has_activity = any(
            int(therapist.get(key, 0)) != 0
            for key in (
                "attendedDays",
                "serviceCount",
                "totalEarnedSatang",
                "paidSatang",
                "outstandingSatang",
            )
        )
        if not therapist_id and not has_activity:
            continue
        rows.append(
            {
                "ชื่อหมอนวด": _spreadsheet_safe(therapist.get("therapistName")),
                "จำนวนวันที่มาทำงาน": int(therapist.get("attendedDays", 0)),
                "จำนวนงาน": int(therapist.get("serviceCount", 0)),
                "เวลานวดรวม (นาที)": int(therapist.get("durationMinutes", 0)),
                "ค่ามือจากบริการ (บาท)": _baht_csv(therapist.get("servicePaySatang")),
                "เงินเติมค่าประกันจากร้าน (บาท)": _baht_csv(
                    therapist.get("guaranteeTopUpSatang")
                ),
                "โบนัส/รายการปรับปรุง (บาท)": _baht_csv(
                    therapist.get("shopAdjustmentSatang")
                ),
                "ทิปหมอ (บาท)": _baht_csv(therapist.get("tipSatang")),
                "รวมรายได้หมอ (บาท)": _baht_csv(therapist.get("totalEarnedSatang")),
                "จ่ายแล้ว (บาท)": _baht_csv(therapist.get("paidSatang")),
                "ค้างจ่าย (บาท)": _baht_csv(therapist.get("outstandingSatang")),
                "สถานะการจ่าย": PAYOUT_STATUS_TH.get(
                    str(therapist.get("payoutState")),
                    str(therapist.get("payoutState") or "ไม่ทราบสถานะ"),
                ),
            }
        )
    return SUMMARY_COMPENSATION_CSV_FIELDS, rows


def _attachment_header(filename: str, fallback: str) -> str:
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}'


@router.get("/therapist-compensation")
def get_therapist_compensation(
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    date_from: Annotated[str, Query(alias="dateFrom")],
    date_to: Annotated[str, Query(alias="dateTo")],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
) -> dict[str, object]:
    _require_admin(actor)
    start, end = _parse_range(date_from, date_to)
    return _load_payload(client, branch_id=branch_id, start=start, end=end)


@router.get("/therapist-compensation/former-outstanding")
def get_former_outstanding(
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
) -> dict[str, object]:
    _require_admin(actor)
    return _former_outstanding_payload(client, branch_id)


@router.post("/therapist-compensation:export")
def export_therapist_compensation(
    request: CompensationExportInput,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> Response:
    _require_admin(actor)
    start, end = _parse_range(request.date_from, request.date_to)
    payload = _load_payload(
        client,
        branch_id=request.branch_id,
        start=start,
        end=end,
    )
    fields, rows = _compensation_export_rows(
        payload,
        request.report_type,
        request.therapist_id,
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    client.collection("audit_events").document().set(
        {
            "eventType": "THERAPIST_COMPENSATION_CSV_EXPORTED",
            "actorId": actor["uid"],
            "actorType": "ADMIN_USER",
            "branchId": request.branch_id,
            "reportType": request.report_type,
            "dateFrom": request.date_from,
            "dateTo": request.date_to,
            "therapistId": request.therapist_id,
            "recordCount": len(rows),
            "createdAt": datetime.now(UTC),
        }
    )
    stem = (
        "ค่าตอบแทนหมอรายวัน"
        if request.report_type == "DAILY_DETAIL"
        else "สรุปยอดจ่ายหมอ"
    )
    fallback_stem = (
        "therapist-compensation-daily"
        if request.report_type == "DAILY_DETAIL"
        else "therapist-compensation-summary"
    )
    filename = f"{stem}_{request.date_from}_ถึง_{request.date_to}.csv"
    fallback = f"{fallback_stem}-{request.date_from}-to-{request.date_to}.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _attachment_header(filename, fallback)},
    )


@router.patch("/therapists/{therapist_id}/compensation-profile")
def update_compensation_profile(
    therapist_id: str,
    request: CompensationProfileUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    _require_admin(actor)
    try:
        date.fromisoformat(request.effective_from)
    except ValueError as error:
        raise ValidationDomainError("Guarantee effective date is invalid") from error
    therapist_ref = client.collection("therapists").document(therapist_id)
    rate_id = hashlib.sha256(
        f"{therapist_id}:{request.effective_from}".encode()
    ).hexdigest()
    rate_ref = client.collection("therapist_guarantee_rates").document(rate_id)
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        snapshot = therapist_ref.get(transaction=tx)
        payouts = _snapshot_items(
            client,
            "therapist_payouts",
            branch_id=str((snapshot.to_dict() or {}).get("branchId", "branch_001"))
            if snapshot.exists
            else "branch_001",
            transaction=tx,
        )
        if not snapshot.exists:
            raise NotFoundDomainError("Therapist not found")
        data = snapshot.to_dict() or {}
        if int(data.get("version", 1)) != request.expected_version:
            raise ConflictDomainError("Therapist changed; reload before trying again")
        if any(
            item.get("therapistId") == therapist_id
            and str(item.get("dateTo", "")) >= request.effective_from
            for item in payouts
        ):
            raise ConflictDomainError(
                "A guarantee rate cannot be changed retroactively across a paid period"
            )
        now = datetime.now(UTC)
        next_version = request.expected_version + 1
        tx.update(
            therapist_ref,
            {
                "dailyGuaranteeSatang": request.daily_guarantee_satang,
                "guaranteeEffectiveFrom": request.effective_from,
                "version": next_version,
                "updatedAt": now,
                "updatedBy": actor["uid"],
            },
        )
        tx.set(
            rate_ref,
            {
                "branchId": data.get("branchId", "branch_001"),
                "therapistId": therapist_id,
                "effectiveFrom": request.effective_from,
                "dailyGuaranteeSatang": request.daily_guarantee_satang,
                "profileVersion": next_version,
                "reason": request.reason.strip(),
                "createdAt": now,
                "createdBy": actor["uid"],
            },
        )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "THERAPIST_COMPENSATION_PROFILE_UPDATED",
                "therapistId": therapist_id,
                "oldDailyGuaranteeSatang": int(
                    data.get("dailyGuaranteeSatang", DEFAULT_DAILY_GUARANTEE_SATANG)
                ),
                "newDailyGuaranteeSatang": request.daily_guarantee_satang,
                "effectiveFrom": request.effective_from,
                "reason": request.reason.strip(),
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "createdAt": now,
            },
        )
        return {
            "therapistId": therapist_id,
            "dailyGuaranteeSatang": request.daily_guarantee_satang,
            "guaranteeEffectiveFrom": request.effective_from,
            "version": next_version,
        }

    return write(transaction)


@router.put("/therapist-compensation/attendance/{therapist_id}/{local_date}")
def update_attendance(
    therapist_id: str,
    local_date: str,
    request: AttendanceUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
) -> dict[str, object]:
    _require_admin(actor)
    try:
        date.fromisoformat(local_date)
    except ValueError as error:
        raise ValidationDomainError("Attendance date is invalid") from error
    therapist_ref = client.collection("therapists").document(therapist_id)
    attendance_id = hashlib.sha256(
        f"{branch_id}:{therapist_id}:{local_date}".encode()
    ).hexdigest()
    attendance_ref = client.collection("therapist_attendance").document(attendance_id)
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        therapist_snapshot = therapist_ref.get(transaction=tx)
        attendance_snapshot = attendance_ref.get(transaction=tx)
        rate_items = _snapshot_items(
            client,
            "therapist_guarantee_rates",
            branch_id=branch_id,
            transaction=tx,
        )
        payouts = _snapshot_items(
            client, "therapist_payouts", branch_id=branch_id, transaction=tx
        )
        if not therapist_snapshot.exists:
            raise NotFoundDomainError("Therapist not found")
        therapist = therapist_snapshot.to_dict() or {}
        if therapist.get("branchId") != branch_id:
            raise ValidationDomainError("Therapist does not belong to branch")
        changed_at = therapist.get("statusChangedAt")
        changed_date = (
            changed_at.astimezone(ZoneInfo("Asia/Bangkok")).date().isoformat()
            if isinstance(changed_at, datetime)
            else None
        )
        if (
            request.present
            and not therapist.get("active")
            and (changed_date is None or local_date >= changed_date)
        ):
            raise ValidationDomainError("Former therapists cannot be marked present after leaving")
        current = attendance_snapshot.to_dict() or {} if attendance_snapshot.exists else {}
        current_version = int(current.get("version", 0))
        if current_version != request.expected_version:
            raise ConflictDomainError("Attendance changed; reload before trying again")
        if _has_payout_covering_date(payouts, therapist_id, local_date):
            raise ConflictDomainError(
                "Paid attendance cannot be overwritten; create a compensation adjustment"
            )
        now = datetime.now(UTC)
        next_version = current_version + 1
        applicable_rates = sorted(
            (
                item
                for item in rate_items
                if item.get("therapistId") == therapist_id
                and str(item.get("effectiveFrom", "")) <= local_date
            ),
            key=lambda item: str(item.get("effectiveFrom", "")),
        )
        guarantee_rate = (
            int(applicable_rates[-1].get("dailyGuaranteeSatang", 0))
            if applicable_rates
            else DEFAULT_DAILY_GUARANTEE_SATANG
        )
        tx.set(
            attendance_ref,
            {
                "branchId": branch_id,
                "therapistId": therapist_id,
                "localDate": local_date,
                "present": request.present,
                "guaranteeRateSatang": guarantee_rate,
                "version": next_version,
                "updatedAt": now,
                "updatedBy": actor["uid"],
                **(
                    {}
                    if attendance_snapshot.exists
                    else {"createdAt": now, "createdBy": actor["uid"]}
                ),
            },
            merge=attendance_snapshot.exists,
        )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "THERAPIST_ATTENDANCE_UPDATED",
                "therapistId": therapist_id,
                "localDate": local_date,
                "present": request.present,
                "guaranteeRateSatang": guarantee_rate,
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "createdAt": now,
            },
        )
        return {
            "therapistId": therapist_id,
            "localDate": local_date,
            "present": request.present,
            "guaranteeRateSatang": guarantee_rate,
            "version": next_version,
        }

    return write(transaction)


def _command_digest(action: str, payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"action": action, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@router.post(
    "/therapist-compensation/adjustments", status_code=status.HTTP_201_CREATED
)
def create_adjustment(
    request: AdjustmentCreate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    _require_admin(actor)
    try:
        date.fromisoformat(request.local_date)
    except ValueError as error:
        raise ValidationDomainError("Adjustment date is invalid") from error
    digest = _command_digest("CREATE_COMPENSATION_ADJUSTMENT", request.model_dump(mode="json"))
    command_ref = client.collection("admin_commands").document(
        hashlib.sha256(request.command_id.encode()).hexdigest()
    )
    adjustment_id = f"adjustment_{uuid4().hex}"
    adjustment_ref = client.collection("therapist_compensation_adjustments").document(
        adjustment_id
    )
    therapist_ref = client.collection("therapists").document(request.therapist_id)
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        command_snapshot = command_ref.get(transaction=tx)
        if command_snapshot.exists:
            command = command_snapshot.to_dict() or {}
            if command.get("requestDigest") != digest:
                raise ConflictDomainError("Command ID was already used with different data")
            response = command.get("response")
            if not isinstance(response, dict):
                raise ConflictDomainError("Stored command response is unavailable")
            return response
        therapist_snapshot = therapist_ref.get(transaction=tx)
        if not therapist_snapshot.exists:
            raise NotFoundDomainError("Therapist not found")
        therapist = therapist_snapshot.to_dict() or {}
        if therapist.get("branchId") != request.branch_id:
            raise ValidationDomainError("Therapist does not belong to branch")
        now = datetime.now(UTC)
        response: dict[str, object] = {
            "entryId": adjustment_id,
            "therapistId": request.therapist_id,
            "localDate": request.local_date,
            "source": "SHOP",
            "kind": request.kind,
            "amountSatang": request.amount_satang,
            "reason": request.reason.strip(),
            "version": 1,
        }
        tx.create(
            adjustment_ref,
            {
                "branchId": request.branch_id,
                "therapistId": request.therapist_id,
                "localDate": request.local_date,
                "kind": request.kind,
                "amountSatang": request.amount_satang,
                "reason": request.reason.strip(),
                "version": 1,
                "createdAt": now,
                "createdBy": actor["uid"],
            },
        )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "THERAPIST_COMPENSATION_ADJUSTMENT_CREATED",
                **response,
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "createdAt": now,
            },
        )
        tx.create(
            command_ref,
            {
                "action": "CREATE_COMPENSATION_ADJUSTMENT",
                "requestDigest": digest,
                "response": response,
                "createdAt": now,
            },
        )
        return response

    return write(transaction)


def _has_payout_covering_date(
    payouts: list[dict[str, object]], therapist_id: str, local_date: str
) -> bool:
    target = date.fromisoformat(local_date)
    for payout in payouts:
        if payout.get("therapistId") != therapist_id:
            continue
        allocations = payout.get("dailyAllocations")
        if isinstance(allocations, list):
            if any(
                isinstance(item, dict)
                and item.get("localDate") == local_date
                and int(item.get("amountSatang", 0)) != 0
                for item in allocations
            ):
                return True
            continue
        try:
            if date.fromisoformat(str(payout.get("dateFrom"))) <= target <= date.fromisoformat(
                str(payout.get("dateTo"))
            ):
                return True
        except ValueError:
            continue
    return False


def _payout_locks_entry(
    payouts: list[dict[str, object]],
    therapist_id: str,
    local_date: str,
    entry_created_at: object,
) -> bool:
    target = date.fromisoformat(local_date)
    for payout in payouts:
        if payout.get("therapistId") != therapist_id:
            continue
        allocations = payout.get("dailyAllocations")
        if isinstance(allocations, list):
            covered = any(
                isinstance(item, dict)
                and item.get("localDate") == local_date
                and int(item.get("amountSatang", 0)) != 0
                for item in allocations
            )
        else:
            try:
                payout_start = date.fromisoformat(str(payout.get("dateFrom")))
                payout_end = date.fromisoformat(str(payout.get("dateTo")))
                covered = payout_start <= target <= payout_end
            except ValueError:
                continue
        if not covered:
            continue
        paid_at = payout.get("paidAt")
        if isinstance(entry_created_at, datetime) and isinstance(paid_at, datetime):
            if entry_created_at <= paid_at:
                return True
            continue
        return True
    return False


@router.patch("/therapist-compensation/adjustments/{adjustment_id}")
def update_adjustment(
    adjustment_id: str,
    request: AdjustmentUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    _require_admin(actor)
    adjustment_ref = client.collection("therapist_compensation_adjustments").document(
        adjustment_id
    )
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        snapshot = adjustment_ref.get(transaction=tx)
        if not snapshot.exists:
            raise NotFoundDomainError("Compensation adjustment not found")
        data = snapshot.to_dict() or {}
        if int(data.get("version", 1)) != request.expected_version:
            raise ConflictDomainError("Adjustment changed; reload before trying again")
        payouts = _snapshot_items(
            client,
            "therapist_payouts",
            branch_id=str(data.get("branchId", "branch_001")),
            transaction=tx,
        )
        if _payout_locks_entry(
            payouts,
            str(data.get("therapistId")),
            str(data.get("localDate")),
            data.get("createdAt"),
        ):
            raise ConflictDomainError(
                "Paid compensation cannot be overwritten; create a new adjustment instead"
            )
        now = datetime.now(UTC)
        next_version = request.expected_version + 1
        tx.update(
            adjustment_ref,
            {
                "amountSatang": request.amount_satang,
                "kind": request.kind,
                "reason": request.reason.strip(),
                "version": next_version,
                "updatedAt": now,
                "updatedBy": actor["uid"],
            },
        )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "THERAPIST_COMPENSATION_ADJUSTMENT_UPDATED",
                "entryId": adjustment_id,
                "therapistId": data.get("therapistId"),
                "oldAmountSatang": int(data.get("amountSatang", 0)),
                "newAmountSatang": request.amount_satang,
                "oldReason": data.get("reason"),
                "reason": request.reason.strip(),
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "createdAt": now,
            },
        )
        return {
            "entryId": adjustment_id,
            "amountSatang": request.amount_satang,
            "kind": request.kind,
            "reason": request.reason.strip(),
            "version": next_version,
        }

    return write(transaction)


@router.post("/therapist-compensation/payouts", status_code=status.HTTP_201_CREATED)
def create_payout(
    request: PayoutCreate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    _require_admin(actor)
    start, end = _parse_range(request.date_from, request.date_to)
    digest = _command_digest("CREATE_THERAPIST_PAYOUT", request.model_dump(mode="json"))
    command_ref = client.collection("admin_commands").document(
        hashlib.sha256(request.command_id.encode()).hexdigest()
    )
    payout_id = f"payout_{uuid4().hex}"
    payout_ref = client.collection("therapist_payouts").document(payout_id)
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> dict[str, object]:
        command_snapshot = command_ref.get(transaction=tx)
        if command_snapshot.exists:
            command = command_snapshot.to_dict() or {}
            if command.get("requestDigest") != digest:
                raise ConflictDomainError("Command ID was already used with different data")
            response = command.get("response")
            if not isinstance(response, dict):
                raise ConflictDomainError("Stored command response is unavailable")
            return response
        payload = _load_payload(
            client,
            branch_id=request.branch_id,
            start=start,
            end=end,
            transaction=tx,
        )
        row = next(
            (
                item
                for item in payload["summary"]
                if item["therapistId"] == request.therapist_id
            ),
            None,
        )
        if not row:
            raise NotFoundDomainError("Therapist not found")
        outstanding = int(row["outstandingSatang"])
        if outstanding <= 0:
            raise ConflictDomainError("No outstanding therapist compensation to pay")
        daily_allocations = [
            {
                "localDate": day_item["localDate"],
                "amountSatang": int(day_item["outstandingSatang"]),
            }
            for day_item in sorted(row["days"], key=lambda item: str(item["localDate"]))
            if int(day_item["outstandingSatang"]) != 0
        ]
        if sum(int(item["amountSatang"]) for item in daily_allocations) != outstanding:
            raise ConflictDomainError(
                "Outstanding compensation could not be reconciled by service date"
            )
        now = datetime.now(UTC)
        response: dict[str, object] = {
            "payoutId": payout_id,
            "therapistId": request.therapist_id,
            "dateFrom": request.date_from,
            "dateTo": request.date_to,
            "amountSatang": outstanding,
            "dailyAllocations": daily_allocations,
            "paymentMethod": request.payment_method,
            "paidAt": now,
        }
        tx.create(
            payout_ref,
            {
                "branchId": request.branch_id,
                **response,
                "note": request.note.strip(),
                "paidBy": actor["uid"],
                "createdAt": now,
            },
        )
        tx.set(
            client.collection("audit_events").document(),
            {
                "eventType": "THERAPIST_PAYOUT_RECORDED",
                **response,
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "createdAt": now,
            },
        )
        tx.create(
            command_ref,
            {
                "action": "CREATE_THERAPIST_PAYOUT",
                "requestDigest": digest,
                "response": response,
                "createdAt": now,
            },
        )
        return response

    return write(transaction)
