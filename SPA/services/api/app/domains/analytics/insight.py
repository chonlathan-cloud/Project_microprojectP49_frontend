from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from typing import Literal


InsightView = Literal["BOOKINGS", "REVENUE", "SERVICES", "THERAPISTS"]
SettlementState = Literal["ALLOCATED", "PENDING", "STALE"]


@dataclass(frozen=True)
class InsightFilters:
    source: str | None = None
    admin_entry_mode: str | None = None
    booking_status: str | None = None
    payment_status: str | None = None
    service_id: str | None = None
    variant_id: str | None = None
    therapist_id: str | None = None
    settlement_state: SettlementState | None = None
    has_discount: bool | None = None
    has_tip: bool | None = None
    hour_from: int | None = None
    hour_to: int | None = None


def allocate_discount(
    groups: list[tuple[tuple[str, str], dict[str, object]]], discount_satang: int
) -> dict[tuple[str, str], int]:
    positive = [(key, max(0, int(value["grossServiceSatang"]))) for key, value in groups]
    subtotal = sum(value for _, value in positive)
    if discount_satang <= 0 or subtotal <= 0:
        return {key: 0 for key, _ in positive}
    result: dict[tuple[str, str], int] = {}
    allocated = 0
    for index, (key, value) in enumerate(positive):
        share = (
            discount_satang - allocated
            if index == len(positive) - 1
            else (discount_satang * value) // subtotal
        )
        result[key] = share
        allocated += share
    return result


def _settlement_state(
    booking: dict[str, object], settlement: dict[str, object] | None
) -> SettlementState:
    if not settlement:
        return "PENDING"
    if int(settlement.get("sourceTipAmountSatang", 0)) != int(
        booking.get("tipAmountSatang", 0)
    ):
        return "STALE"
    return "ALLOCATED"


def _service_groups(
    lines: list[dict[str, object]],
) -> dict[str, dict[tuple[str, str], dict[str, object]]]:
    result: dict[str, dict[tuple[str, str], dict[str, object]]] = defaultdict(dict)
    for line in lines:
        booking_id = str(line.get("bookingDocId", ""))
        service = line.get("serviceSnapshot")
        if not booking_id or not isinstance(service, dict):
            continue
        service_id = str(service.get("serviceId", "unknown"))
        variant_id = str(service.get("variantId", "unknown"))
        key = (service_id, variant_id)
        group = result[booking_id].setdefault(
            key,
            {
                "serviceId": service_id,
                "variantId": variant_id,
                "serviceNameTh": service.get("nameTh") or service.get("nameEn") or service_id,
                "serviceNameEn": service.get("nameEn") or service.get("nameTh") or service_id,
                "durationMinutes": int(service.get("durationMinutes", 0)),
                "grossServiceSatang": 0,
                "participantIds": set(),
            },
        )
        group["grossServiceSatang"] = int(group["grossServiceSatang"]) + int(
            line.get("lineTotalSatang", 0)
        )
        participant_ids = group["participantIds"]
        if isinstance(participant_ids, set):
            participant_ids.update(str(item) for item in line.get("participantIds") or [])
    return result


def _matches_filters(
    booking: dict[str, object],
    groups: dict[tuple[str, str], dict[str, object]],
    settlement: dict[str, object] | None,
    filters: InsightFilters,
) -> bool:
    if filters.source and booking.get("source") != filters.source:
        return False
    if filters.admin_entry_mode and booking.get("adminEntryMode") != filters.admin_entry_mode:
        return False
    if filters.booking_status and booking.get("status") != filters.booking_status:
        return False
    if filters.payment_status and booking.get("paymentStatus", "UNAVAILABLE") != filters.payment_status:
        return False
    if filters.has_discount is not None:
        if (int(booking.get("discountAmountSatang", 0)) > 0) != filters.has_discount:
            return False
    if filters.has_tip is not None:
        if (int(booking.get("tipAmountSatang", 0)) > 0) != filters.has_tip:
            return False
    local_time = str(booking.get("localStartTime", ""))
    try:
        hour = int(local_time[:2])
    except (TypeError, ValueError):
        hour = None
    if filters.hour_from is not None and (hour is None or hour < filters.hour_from):
        return False
    if filters.hour_to is not None and (hour is None or hour > filters.hour_to):
        return False
    if filters.service_id and not any(
        group.get("serviceId") == filters.service_id for group in groups.values()
    ):
        return False
    if filters.variant_id and not any(
        group.get("variantId") == filters.variant_id for group in groups.values()
    ):
        return False
    state = _settlement_state(booking, settlement)
    if filters.settlement_state and state != filters.settlement_state:
        return False
    if filters.therapist_id:
        allocations = settlement.get("allocations") if settlement else []
        if not any(
            isinstance(item, dict) and item.get("therapistId") == filters.therapist_id
            for item in allocations or []
        ):
            return False
    return True


def _booking_row(
    document_id: str,
    booking: dict[str, object],
    groups: dict[tuple[str, str], dict[str, object]],
    settlement: dict[str, object] | None,
) -> dict[str, object]:
    state = _settlement_state(booking, settlement)
    valid_settlement = settlement if state == "ALLOCATED" else {}
    allocations = valid_settlement.get("allocations") if valid_settlement else []
    therapist_names = sorted(
        {
            str(item.get("therapistName") or item.get("therapistId"))
            for item in allocations or []
            if isinstance(item, dict) and (item.get("therapistName") or item.get("therapistId"))
        }
    )
    service_names_th = [str(item["serviceNameTh"]) for item in groups.values()]
    service_names_en = [str(item["serviceNameEn"]) for item in groups.values()]
    net = int(booking.get("estimatedAmountSatang", 0))
    tip = int(booking.get("tipAmountSatang", 0))
    gross = int(booking.get("grossAmountSatang", net + tip))
    paid = int(booking.get("paidAmountSatang", 0))
    return {
        "bookingId": booking.get("publicBookingId", document_id),
        "localDate": booking.get("localDate"),
        "localStartTime": booking.get("localStartTime"),
        "status": booking.get("status"),
        "source": booking.get("source"),
        "adminEntryMode": booking.get("adminEntryMode"),
        "serviceNamesTh": service_names_th,
        "serviceNamesEn": service_names_en,
        "pax": int(booking.get("pax", 1)),
        "subtotalAmountSatang": int(booking.get("subtotalAmountSatang", 0)),
        "discountAmountSatang": int(booking.get("discountAmountSatang", 0)),
        "netServiceAmountSatang": net,
        "tipAmountSatang": tip,
        "grossAmountSatang": gross,
        "paymentStatus": booking.get("paymentStatus", "UNAVAILABLE"),
        "paidAmountSatang": paid,
        "outstandingAmountSatang": max(0, gross - paid),
        "settlementState": state,
        "therapistNames": therapist_names,
        "therapistPaySatang": int(valid_settlement.get("therapistPaySatang", 0)),
        "therapistTipSatang": int(valid_settlement.get("therapistTipSatang", 0)),
        "shopTotalSatang": int(valid_settlement.get("shopTotalSatang", 0)),
    }


def _revenue_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    daily: dict[str, dict[str, object]] = {}
    for row in rows:
        local_date = str(row.get("localDate") or "")
        item = daily.setdefault(
            local_date,
            {
                "localDate": local_date,
                "bookingCount": 0,
                "netServiceAmountSatang": 0,
                "tipAmountSatang": 0,
                "grossAmountSatang": 0,
                "paidAmountSatang": 0,
                "outstandingAmountSatang": 0,
                "therapistPaySatang": 0,
                "therapistTipSatang": 0,
                "shopTotalSatang": 0,
            },
        )
        item["bookingCount"] = int(item["bookingCount"]) + 1
        for key in (
            "netServiceAmountSatang",
            "tipAmountSatang",
            "grossAmountSatang",
            "paidAmountSatang",
            "outstandingAmountSatang",
            "therapistPaySatang",
            "therapistTipSatang",
            "shopTotalSatang",
        ):
            item[key] = int(item[key]) + int(row.get(key, 0))
    return [daily[key] for key in sorted(daily, reverse=True)]


def _service_rows(
    booking_ids: list[str],
    bookings: dict[str, dict[str, object]],
    service_groups: dict[str, dict[tuple[str, str], dict[str, object]]],
) -> list[dict[str, object]]:
    services: dict[tuple[str, str], dict[str, object]] = {}
    for booking_id in booking_ids:
        groups = service_groups.get(booking_id, {})
        ordered = sorted(groups.items(), key=lambda item: item[0])
        discount_shares = allocate_discount(
            ordered, int(bookings[booking_id].get("discountAmountSatang", 0))
        )
        for key, group in ordered:
            row = services.setdefault(
                key,
                {
                    "serviceId": group["serviceId"],
                    "variantId": group["variantId"],
                    "serviceNameTh": group["serviceNameTh"],
                    "serviceNameEn": group["serviceNameEn"],
                    "durationMinutes": group["durationMinutes"],
                    "sessionCount": 0,
                    "participantCount": 0,
                    "grossServiceSatang": 0,
                    "discountAllocatedSatang": 0,
                    "netServiceSatang": 0,
                },
            )
            gross = int(group["grossServiceSatang"])
            discount = discount_shares.get(key, 0)
            row["sessionCount"] = int(row["sessionCount"]) + 1
            participants = group.get("participantIds")
            row["participantCount"] = int(row["participantCount"]) + (
                len(participants) if isinstance(participants, set) else 0
            )
            row["grossServiceSatang"] = int(row["grossServiceSatang"]) + gross
            row["discountAllocatedSatang"] = int(row["discountAllocatedSatang"]) + discount
            row["netServiceSatang"] = int(row["netServiceSatang"]) + gross - discount
    return sorted(
        services.values(),
        key=lambda item: (-int(item["sessionCount"]), -int(item["netServiceSatang"])),
    )


def _therapist_rows(
    booking_ids: list[str], settlements: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    therapists: dict[str, dict[str, object]] = {}
    for booking_id in booking_ids:
        settlement = settlements.get(booking_id)
        if not settlement:
            continue
        for allocation in settlement.get("allocations") or []:
            if not isinstance(allocation, dict) or not allocation.get("therapistId"):
                continue
            therapist_id = str(allocation["therapistId"])
            row = therapists.setdefault(
                therapist_id,
                {
                    "therapistId": therapist_id,
                    "therapistName": allocation.get("therapistName") or therapist_id,
                    "serviceCount": 0,
                    "durationMinutes": 0,
                    "therapistPaySatang": 0,
                    "tipSatang": 0,
                },
            )
            row["serviceCount"] = int(row["serviceCount"]) + 1
            row["durationMinutes"] = int(row["durationMinutes"]) + int(
                allocation.get("durationMinutes", 0)
            )
            row["therapistPaySatang"] = int(row["therapistPaySatang"]) + int(
                allocation.get("therapistPaySatang", 0)
            )
            row["tipSatang"] = int(row["tipSatang"]) + int(
                allocation.get("tipShareSatang", 0)
            )
    return sorted(
        therapists.values(),
        key=lambda item: (-int(item["therapistPaySatang"]), str(item["therapistName"])),
    )


def build_insight_payload(
    *,
    bookings: dict[str, dict[str, object]],
    lines: list[dict[str, object]],
    settlements: dict[str, dict[str, object]],
    filters: InsightFilters,
    view: InsightView,
    page: int,
    page_size: int,
) -> dict[str, object]:
    service_groups = _service_groups(lines)
    matched_ids = [
        document_id
        for document_id, booking in bookings.items()
        if booking.get("status") in {"COMPLETED", "RECORDED"}
        and not bool(booking.get("financiallyExcluded"))
        and _matches_filters(
            booking,
            service_groups.get(document_id, {}),
            settlements.get(document_id),
            filters,
        )
    ]
    matched_ids.sort(
        key=lambda item: (
            str(bookings[item].get("localDate", "")),
            str(bookings[item].get("localStartTime", "")),
            str(bookings[item].get("publicBookingId", item)),
        ),
        reverse=True,
    )
    booking_rows = [
        _booking_row(
            document_id,
            bookings[document_id],
            service_groups.get(document_id, {}),
            settlements.get(document_id),
        )
        for document_id in matched_ids
    ]
    summary = {
        "bookingCount": len(booking_rows),
        "netServiceAmountSatang": sum(int(item["netServiceAmountSatang"]) for item in booking_rows),
        "tipAmountSatang": sum(int(item["tipAmountSatang"]) for item in booking_rows),
        "grossAmountSatang": sum(int(item["grossAmountSatang"]) for item in booking_rows),
        "paidAmountSatang": sum(int(item["paidAmountSatang"]) for item in booking_rows),
        "outstandingAmountSatang": sum(int(item["outstandingAmountSatang"]) for item in booking_rows),
        "therapistPaySatang": sum(int(item["therapistPaySatang"]) for item in booking_rows),
        "therapistTipSatang": sum(int(item["therapistTipSatang"]) for item in booking_rows),
        "shopTotalSatang": sum(int(item["shopTotalSatang"]) for item in booking_rows),
        "settlementPendingCount": sum(item["settlementState"] != "ALLOCATED" for item in booking_rows),
    }
    if view == "REVENUE":
        items = _revenue_rows(booking_rows)
    elif view == "SERVICES":
        items = _service_rows(matched_ids, bookings, service_groups)
    elif view == "THERAPISTS":
        valid_settlements = {
            booking_id: settlement
            for booking_id, settlement in settlements.items()
            if booking_id in matched_ids
            and _settlement_state(bookings[booking_id], settlement) == "ALLOCATED"
        }
        items = _therapist_rows(matched_ids, valid_settlements)
    else:
        items = booking_rows

    total_items = len(items)
    total_pages = max(1, ceil(total_items / page_size))
    safe_page = min(page, total_pages)
    start = (safe_page - 1) * page_size
    return {
        "view": view,
        "summary": summary,
        "items": items[start : start + page_size],
        "pagination": {
            "page": safe_page,
            "pageSize": page_size,
            "totalItems": total_items,
            "totalPages": total_pages,
        },
    }
