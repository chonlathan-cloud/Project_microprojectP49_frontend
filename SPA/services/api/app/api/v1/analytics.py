from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_admin_user
from app.core.errors import ConflictDomainError, NotFoundDomainError, ValidationDomainError
from app.domains.analytics.insight import (
    InsightFilters,
    InsightView,
    build_insight_payload,
    settlement_state,
)
from app.domains.analytics.insight import (
    allocate_discount as _allocate_discount,
)
from app.domains.settlements.service import (
    SettlementAllocation,
    calculate_settlement_totals,
)
from app.infrastructure.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1/admin", tags=["admin-analytics"])
SETTLEMENT_ELIGIBLE_STATUSES = {"COMPLETED", "RECORDED"}
ANALYTICS_MAX_DAYS = 366
BANGKOK = ZoneInfo("Asia/Bangkok")


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class SettlementAllocationInput(ApiModel):
    participant_id: str = Field(min_length=1)
    booking_line_item_id: str | None = Field(default=None, min_length=1, max_length=160)
    therapist_id: str | None = None
    therapist_pay_satang: int = Field(ge=0, multiple_of=100)
    tip_share_satang: int = Field(ge=0, multiple_of=100)


class SettlementInput(ApiModel):
    expected_version: int = Field(ge=0)
    allocations: list[SettlementAllocationInput] = Field(min_length=1, max_length=50)
    correction_reason: str | None = Field(default=None, min_length=1, max_length=300)


class InsightExportInput(ApiModel):
    date_from: str
    date_to: str
    branch_id: str = "branch_001"
    view: Literal["BOOKINGS", "REVENUE", "SERVICES", "THERAPISTS"] = "BOOKINGS"
    source: Literal["GUEST_WEB", "LINE_CUSTOMER", "ADMIN_WEB"] | None = None
    admin_entry_mode: Literal["WALK_IN", "STAFF_ASSISTED", "HISTORICAL_RECORD"] | None = None
    booking_status: Literal["COMPLETED", "RECORDED"] | None = None
    payment_status: str | None = Field(default=None, max_length=40)
    service_id: str | None = Field(default=None, max_length=160)
    variant_id: str | None = Field(default=None, max_length=160)
    therapist_id: str | None = Field(default=None, max_length=160)
    settlement_state: Literal["ALLOCATED", "PENDING", "STALE"] | None = None
    has_discount: bool | None = None
    has_tip: bool | None = None
    hour_from: int | None = Field(default=None, ge=0, le=23)
    hour_to: int | None = Field(default=None, ge=0, le=23)


def _require_admin(actor: dict[str, object]) -> None:
    if actor.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="ADMIN role is required")


def _payout_covers_service_date(
    payout: dict[str, object], *, therapist_ids: set[str], service_date: str
) -> bool:
    if str(payout.get("therapistId") or "") not in therapist_ids:
        return False
    daily_allocations = payout.get("dailyAllocations")
    if isinstance(daily_allocations, list):
        return any(
            isinstance(item, dict)
            and item.get("localDate") == service_date
            and int(item.get("amountSatang", 0)) != 0
            for item in daily_allocations
        )
    return (
        str(payout.get("dateFrom") or "") <= service_date
        and str(payout.get("dateTo") or "") >= service_date
    )


def _booking_snapshot(
    client: firestore.Client, booking_id: str
) -> firestore.DocumentSnapshot:
    matches = list(
        client.collection("bookings")
        .where("publicBookingId", "==", booking_id)
        .limit(1)
        .stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking not found")
    return matches[0]


def _booking_children(
    client: firestore.Client, booking_doc_id: str
) -> tuple[list[firestore.DocumentSnapshot], list[firestore.DocumentSnapshot]]:
    participants = list(
        client.collection("booking_participants")
        .where("bookingDocId", "==", booking_doc_id)
        .stream()
    )
    participants.sort(key=lambda item: int((item.to_dict() or {}).get("sequence", 0)))
    lines = list(
        client.collection("booking_line_items")
        .where("bookingDocId", "==", booking_doc_id)
        .stream()
    )
    return participants, lines


def _allocation_lines(
    lines: list[firestore.DocumentSnapshot],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for snapshot in lines:
        line = snapshot.to_dict() or {}
        if line.get("financiallyExcluded"):
            continue
        service = line.get("serviceSnapshot")
        if not isinstance(service, dict):
            continue
        for participant_id in line.get("participantIds") or []:
            if participant_id:
                assignment = line.get("assignment")
                result.append(
                    {
                        "bookingLineItemId": snapshot.id,
                        "participantId": str(participant_id),
                        "sequence": int(line.get("sequence", 0)),
                        "source": line.get("source", "ORIGINAL"),
                        "lineTotalSatang": int(line.get("lineTotalSatang", 0)),
                        "assignment": assignment if isinstance(assignment, dict) else {},
                        **service,
                    }
                )
    return result


def _settlement_response(
    *,
    booking_snapshot: firestore.DocumentSnapshot,
    participants: list[firestore.DocumentSnapshot],
    lines: list[firestore.DocumentSnapshot],
    settlement_snapshot: firestore.DocumentSnapshot,
    therapist_names: dict[str, str],
) -> dict[str, object]:
    booking = booking_snapshot.to_dict() or {}
    settlement = settlement_snapshot.to_dict() if settlement_snapshot.exists else {}
    settlement = settlement or {}
    allocation_lines = _allocation_lines(lines)
    participant_map = {
        snapshot.id: snapshot.to_dict() or {} for snapshot in participants
    }
    participant_order = {snapshot.id: index for index, snapshot in enumerate(participants)}
    allocation_lines.sort(
        key=lambda line: (
            int(line.get("sequence", 0))
            or participant_order.get(str(line["participantId"]), 0) + 1,
            str(line["bookingLineItemId"]),
        )
    )
    existing_by_line = {
        str(item.get("bookingLineItemId")): item
        for item in settlement.get("allocations") or []
        if isinstance(item, dict) and item.get("bookingLineItemId")
    }
    existing_by_participant = {
        str(item.get("participantId")): item
        for item in settlement.get("allocations") or []
        if isinstance(item, dict) and item.get("participantId")
    }
    assigned_ids = [str(value) for value in booking.get("therapistIds") or []]
    rows: list[dict[str, object]] = []
    for index, line in enumerate(allocation_lines):
        participant_id = str(line["participantId"])
        participant = participant_map.get(participant_id, {})
        line_item_id = str(line["bookingLineItemId"])
        existing = existing_by_line.get(line_item_id, {})
        if not existing and sum(
            1 for item in allocation_lines if item["participantId"] == participant_id
        ) == 1:
            existing = existing_by_participant.get(participant_id, {})
        assignment = line.get("assignment")
        assignment_data = assignment if isinstance(assignment, dict) else {}
        therapist_id = existing.get("therapistId")
        if therapist_id is None:
            therapist_id = assignment_data.get("therapistId")
        participant_index = participant_order.get(participant_id, index)
        if therapist_id is None and participant_index < len(assigned_ids):
            therapist_id = assigned_ids[participant_index]
        therapist_id = str(therapist_id) if therapist_id else None
        rows.append(
            {
                "participantId": participant_id,
                "participantSequence": int(participant.get("sequence", index + 1)),
                "participantName": participant.get("nickname") or f"Guest {index + 1}",
                "bookingLineItemId": line_item_id,
                "serviceId": line.get("serviceId") or booking.get("serviceId"),
                "variantId": line.get("variantId"),
                "serviceNameTh": line.get("nameTh") or booking.get("serviceNameTh"),
                "serviceNameEn": line.get("nameEn") or booking.get("serviceNameEn"),
                "durationMinutes": int(line.get("durationMinutes", 0)),
                "therapistId": therapist_id,
                "therapistName": therapist_names.get(
                    therapist_id or "", str(existing.get("therapistName") or "")
                )
                or None,
                "therapistPaySatang": int(existing.get("therapistPaySatang", 0)),
                "tipShareSatang": int(existing.get("tipShareSatang", 0)),
            }
        )

    tip_amount = int(booking.get("tipAmountSatang", 0))
    settled = settlement_snapshot.exists
    source_tip = int(settlement.get("sourceTipAmountSatang", 0)) if settled else 0
    financial_stale = settled and settlement_state(booking, settlement) == "STALE"
    return {
        "bookingId": booking.get("publicBookingId", booking_snapshot.id),
        "bookingStatus": booking.get("status"),
        "eligible": booking.get("status") in SETTLEMENT_ELIGIBLE_STATUSES
        and not bool(booking.get("financiallyExcluded")),
        "settled": settled,
        "requiresTipReallocation": settled and source_tip != tip_amount,
        "requiresFinancialReallocation": financial_stale,
        "version": int(settlement.get("version", 0)),
        "subtotalAmountSatang": int(booking.get("subtotalAmountSatang", 0)),
        "discountAmountSatang": int(booking.get("discountAmountSatang", 0)),
        "netServiceAmountSatang": int(booking.get("estimatedAmountSatang", 0)),
        "tipAmountSatang": tip_amount,
        "grossAmountSatang": int(
            booking.get(
                "grossAmountSatang",
                int(booking.get("estimatedAmountSatang", 0)) + tip_amount,
            )
        ),
        "therapistPaySatang": int(settlement.get("therapistPaySatang", 0)),
        "therapistTipSatang": int(settlement.get("therapistTipSatang", 0)),
        "shopServiceAmountSatang": int(
            settlement.get("shopServiceAmountSatang", booking.get("estimatedAmountSatang", 0))
        ),
        "shopTipSatang": int(settlement.get("shopTipSatang", tip_amount)),
        "shopTotalSatang": int(
            settlement.get(
                "shopTotalSatang", int(booking.get("estimatedAmountSatang", 0)) + tip_amount
            )
        ),
        "negativeShopServiceAmount": bool(
            settlement.get("negativeShopServiceAmount", False)
        ),
        "allocations": rows,
    }


@router.get("/bookings/{booking_id}/settlement")
def get_booking_settlement(
    booking_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    _require_admin(actor)
    booking_snapshot = _booking_snapshot(client, booking_id)
    booking = booking_snapshot.to_dict() or {}
    if booking.get("status") not in SETTLEMENT_ELIGIBLE_STATUSES or booking.get(
        "financiallyExcluded"
    ):
        raise ValidationDomainError(
            "Only completed or active historical records can be financially settled"
        )
    participants, lines = _booking_children(client, booking_snapshot.id)
    if not participants:
        raise ValidationDomainError("Booking participants are unavailable")
    settlement_snapshot = (
        client.collection("service_settlements").document(booking_snapshot.id).get()
    )
    therapist_names = {
        item.id: str((item.to_dict() or {}).get("displayName", item.id))
        for item in client.collection("therapists")
        .where("branchId", "==", booking.get("branchId", "branch_001"))
        .stream()
    }
    return _settlement_response(
        booking_snapshot=booking_snapshot,
        participants=participants,
        lines=lines,
        settlement_snapshot=settlement_snapshot,
        therapist_names=therapist_names,
    )


@router.put("/bookings/{booking_id}/settlement")
def save_booking_settlement(
    booking_id: str,
    request: SettlementInput,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    _require_admin(actor)
    booking_snapshot = _booking_snapshot(client, booking_id)
    participants, lines = _booking_children(client, booking_snapshot.id)
    participant_ids = {item.id for item in participants}
    allocation_lines = _allocation_lines(lines)
    lines_by_id = {str(item["bookingLineItemId"]): item for item in allocation_lines}
    lines_by_participant: dict[str, list[dict[str, object]]] = defaultdict(list)
    for line in allocation_lines:
        lines_by_participant[str(line["participantId"])].append(line)
    resolved_line_ids: list[str] = []
    for item in request.allocations:
        if item.participant_id not in participant_ids:
            raise ValidationDomainError("Settlement participant does not belong to Booking")
        if item.booking_line_item_id:
            line = lines_by_id.get(item.booking_line_item_id)
            if not line or line["participantId"] != item.participant_id:
                raise ValidationDomainError(
                    "Settlement service line does not belong to participant"
                )
            resolved_line_ids.append(item.booking_line_item_id)
            continue
        participant_lines = lines_by_participant.get(item.participant_id, [])
        if len(participant_lines) != 1:
            raise ValidationDomainError(
                "Booking line item ID is required when a participant has multiple services"
            )
        resolved_line_ids.append(str(participant_lines[0]["bookingLineItemId"]))
    if (
        set(resolved_line_ids) != set(lines_by_id)
        or len(resolved_line_ids) != len(request.allocations)
    ):
        raise ValidationDomainError("Every Booking service must be allocated exactly once")

    allocation_inputs = tuple(
        SettlementAllocation(
            participant_id=item.participant_id,
            therapist_id=item.therapist_id,
            therapist_pay_satang=item.therapist_pay_satang,
            tip_share_satang=item.tip_share_satang,
            booking_line_item_id=line_item_id,
        )
        for item, line_item_id in zip(request.allocations, resolved_line_ids, strict=True)
    )
    settlement_ref = client.collection("service_settlements").document(booking_snapshot.id)
    booking_ref = booking_snapshot.reference
    transaction = client.transaction()

    @firestore.transactional
    def write(tx: firestore.Transaction) -> None:
        current_booking_snapshot = booking_ref.get(transaction=tx)
        current_booking = current_booking_snapshot.to_dict() or {}
        current_settlement_snapshot = settlement_ref.get(transaction=tx)
        current_settlement = (
            current_settlement_snapshot.to_dict() or {}
            if current_settlement_snapshot.exists
            else {}
        )
        current_version = int(current_settlement.get("version", 0))
        if current_version != request.expected_version:
            raise ConflictDomainError("Settlement changed; reload before trying again")
        if current_booking.get("status") not in SETTLEMENT_ELIGIBLE_STATUSES or current_booking.get(
            "financiallyExcluded"
        ):
            raise ValidationDomainError(
                "Only completed or active historical records can be financially settled"
            )

        therapist_ids = sorted(
            {item.therapist_id for item in allocation_inputs if item.therapist_id}
        )
        therapist_snapshots = {
            therapist_id: client.collection("therapists")
            .document(therapist_id)
            .get(transaction=tx)
            for therapist_id in therapist_ids
        }
        if any(not snapshot.exists for snapshot in therapist_snapshots.values()):
            raise ValidationDomainError("Every selected therapist must exist")
        if any(
            (snapshot.to_dict() or {}).get("branchId")
            != current_booking.get("branchId", "branch_001")
            for snapshot in therapist_snapshots.values()
        ):
            raise ValidationDomainError(
                "Every selected therapist must belong to the Booking branch"
            )
        therapist_names = {
            therapist_id: str((snapshot.to_dict() or {}).get("displayName", therapist_id))
            for therapist_id, snapshot in therapist_snapshots.items()
        }
        service_date = str(current_booking.get("localDate") or "")
        paid_therapist_ids = {
            str(item.get("therapistId"))
            for item in current_settlement.get("allocations") or []
            if isinstance(item, dict) and item.get("therapistId")
        } | {item.therapist_id for item in allocation_inputs if item.therapist_id}
        payout_snapshots = list(
            client.collection("therapist_payouts")
            .where(
                "branchId", "==", current_booking.get("branchId", "branch_001")
            )
            .stream(transaction=tx)
        )
        if service_date and any(
            _payout_covers_service_date(
                snapshot.to_dict() or {},
                therapist_ids=paid_therapist_ids,
                service_date=service_date,
            )
            for snapshot in payout_snapshots
        ):
            raise ConflictDomainError(
                "Paid therapist compensation cannot be overwritten; create an adjustment"
            )
        net_service_amount = int(current_booking.get("estimatedAmountSatang", 0))
        tip_amount = int(current_booking.get("tipAmountSatang", 0))
        totals = calculate_settlement_totals(
            net_service_amount_satang=net_service_amount,
            source_tip_amount_satang=tip_amount,
            allocations=allocation_inputs,
        )
        now = datetime.now(UTC)
        next_version = current_version + 1
        rows: list[dict[str, object]] = []
        for allocation in allocation_inputs:
            participant = next(
                (item for item in participants if item.id == allocation.participant_id), None
            )
            participant_data = participant.to_dict() or {} if participant else {}
            line = lines_by_id.get(allocation.booking_line_item_id or "", {})
            rows.append(
                {
                    "participantId": allocation.participant_id,
                    "participantSequence": int(participant_data.get("sequence", 0)),
                    "bookingLineItemId": allocation.booking_line_item_id,
                    "serviceId": line.get("serviceId") or current_booking.get("serviceId"),
                    "variantId": line.get("variantId"),
                    "serviceNameTh": line.get("nameTh") or current_booking.get("serviceNameTh"),
                    "serviceNameEn": line.get("nameEn") or current_booking.get("serviceNameEn"),
                    "durationMinutes": int(line.get("durationMinutes", 0)),
                    "therapistId": allocation.therapist_id,
                    "therapistName": therapist_names.get(allocation.therapist_id or ""),
                    "therapistPaySatang": allocation.therapist_pay_satang,
                    "tipShareSatang": allocation.tip_share_satang,
                }
            )
        data = {
            "bookingDocId": booking_snapshot.id,
            "bookingPublicId": current_booking.get("publicBookingId", booking_id),
            "branchId": current_booking.get("branchId", "branch_001"),
            "serviceDate": current_booking.get("localDate"),
            "bookingStatus": current_booking.get("status"),
            "sourceBookingVersion": int(current_booking.get("version", 1)),
            "subtotalAmountSatang": int(current_booking.get("subtotalAmountSatang", 0)),
            "discountAmountSatang": int(current_booking.get("discountAmountSatang", 0)),
            "netServiceAmountSatang": totals.net_service_amount_satang,
            "sourceTipAmountSatang": totals.source_tip_amount_satang,
            "therapistPaySatang": totals.therapist_pay_satang,
            "therapistTipSatang": totals.therapist_tip_satang,
            "shopServiceAmountSatang": totals.shop_service_amount_satang,
            "shopTipSatang": totals.shop_tip_satang,
            "shopTotalSatang": totals.shop_total_satang,
            "negativeShopServiceAmount": totals.negative_shop_service_amount,
            "allocations": rows,
            "state": "ALLOCATED",
            "version": next_version,
            "updatedAt": now,
            "updatedBy": actor["uid"],
        }
        if not current_settlement_snapshot.exists:
            data["createdAt"] = now
            data["createdBy"] = actor["uid"]
        tx.set(settlement_ref, data, merge=current_settlement_snapshot.exists)
        tx.update(
            booking_ref,
            {
                "financialSettlementStatus": "ALLOCATED",
                "financialSettlementVersion": next_version,
                "financialSettlementUpdatedAt": now,
            },
        )
        audit_ref = client.collection("audit_events").document()
        tx.set(
            audit_ref,
            {
                "eventType": "SERVICE_SETTLEMENT_RECORDED",
                "bookingDocId": booking_snapshot.id,
                "publicBookingId": booking_id,
                "actorType": "ADMIN_USER",
                "actorId": actor["uid"],
                "settlementVersion": next_version,
                "netServiceAmountSatang": totals.net_service_amount_satang,
                "sourceTipAmountSatang": totals.source_tip_amount_satang,
                "therapistPaySatang": totals.therapist_pay_satang,
                "correctionReason": request.correction_reason,
                "therapistTipSatang": totals.therapist_tip_satang,
                "shopServiceAmountSatang": totals.shop_service_amount_satang,
                "shopTipSatang": totals.shop_tip_satang,
                "negativeShopServiceAmount": totals.negative_shop_service_amount,
                "createdAt": now,
            },
        )

    write(transaction)
    refreshed_booking = booking_ref.get()
    refreshed_settlement = settlement_ref.get()
    therapist_names = {
        item.id: str((item.to_dict() or {}).get("displayName", item.id))
        for item in client.collection("therapists")
        .where("branchId", "==", (refreshed_booking.to_dict() or {}).get("branchId"))
        .stream()
    }
    return _settlement_response(
        booking_snapshot=refreshed_booking,
        participants=participants,
        lines=lines,
        settlement_snapshot=refreshed_settlement,
        therapist_names=therapist_names,
    )


def _validate_date_range(date_from: str, date_to: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError as error:
        raise ValidationDomainError("Analytics date range is invalid") from error
    if end < start:
        raise ValidationDomainError("Analytics end date cannot be before start date")
    if (end - start).days >= ANALYTICS_MAX_DAYS:
        raise ValidationDomainError("Analytics date range cannot exceed 366 days")
    return start, end


def _related_documents(
    client: firestore.Client, collection_name: str, booking_doc_ids: list[str]
) -> list[firestore.DocumentSnapshot]:
    items: list[firestore.DocumentSnapshot] = []
    for index in range(0, len(booking_doc_ids), 30):
        chunk = booking_doc_ids[index : index + 30]
        if not chunk:
            continue
        items.extend(
            client.collection(collection_name)
            .where("bookingDocId", "in", chunk)
            .stream()
        )
    return items


@router.get("/analytics/overview")
def analytics_overview(
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    date_from: Annotated[str, Query(alias="dateFrom")],
    date_to: Annotated[str, Query(alias="dateTo")],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
) -> dict[str, object]:
    _require_admin(actor)
    _validate_date_range(date_from, date_to)
    booking_snapshots = list(
        client.collection("bookings")
        .where("branchId", "==", branch_id)
        .where("localDate", ">=", date_from)
        .where("localDate", "<=", date_to)
        .stream()
    )
    bookings = {snapshot.id: snapshot.to_dict() or {} for snapshot in booking_snapshots}
    eligible_ids = [
        document_id
        for document_id, booking in bookings.items()
        if booking.get("status") in SETTLEMENT_ELIGIBLE_STATUSES
        and not bool(booking.get("financiallyExcluded"))
    ]
    line_snapshots = _related_documents(client, "booking_line_items", eligible_ids)
    settlement_snapshots = list(
        client.get_all(
            [client.collection("service_settlements").document(item) for item in eligible_ids]
        )
    ) if eligible_ids else []
    settlements = {
        snapshot.id: snapshot.to_dict() or {}
        for snapshot in settlement_snapshots
        if snapshot.exists
    }

    service_revenue = sum(
        int(bookings[item].get("estimatedAmountSatang", 0)) for item in eligible_ids
    )
    tips = sum(int(bookings[item].get("tipAmountSatang", 0)) for item in eligible_ids)
    historical_recorded_gross = sum(
        int(
            bookings[item].get(
                "grossAmountSatang",
                int(bookings[item].get("estimatedAmountSatang", 0))
                + int(bookings[item].get("tipAmountSatang", 0)),
            )
        )
        for item in eligible_ids
        if bookings[item].get("status") == "RECORDED"
    )
    verified_collected = sum(
        int(booking.get("paidAmountSatang", 0))
        for booking in bookings.values()
        if booking.get("status") == "COMPLETED" and booking.get("paymentStatus") == "PAID"
    )
    outstanding = sum(
        max(
            0,
            int(
                booking.get(
                    "grossAmountSatang",
                    int(booking.get("estimatedAmountSatang", 0))
                    + int(booking.get("tipAmountSatang", 0)),
                )
            )
            - int(booking.get("paidAmountSatang", 0)),
        )
        for booking in bookings.values()
        if booking.get("status") == "COMPLETED" and booking.get("paymentStatus") != "PAID"
    )

    complete_settlements: dict[str, dict[str, object]] = {}
    for booking_id in eligible_ids:
        settlement = settlements.get(booking_id)
        if settlement and settlement_state(bookings[booking_id], settlement) == "ALLOCATED":
            complete_settlements[booking_id] = settlement
    therapist_pay = sum(
        int(item.get("therapistPaySatang", 0)) for item in complete_settlements.values()
    )
    therapist_tip = sum(
        int(item.get("therapistTipSatang", 0)) for item in complete_settlements.values()
    )
    shop_service = sum(
        int(item.get("shopServiceAmountSatang", 0)) for item in complete_settlements.values()
    )
    shop_tip = sum(int(item.get("shopTipSatang", 0)) for item in complete_settlements.values())

    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"serviceRevenueSatang": 0, "tipSatang": 0, "bookingCount": 0}
    )
    for booking_id in eligible_ids:
        booking = bookings[booking_id]
        local_date = str(booking.get("localDate", ""))
        daily[local_date]["serviceRevenueSatang"] += int(
            booking.get("estimatedAmountSatang", 0)
        )
        daily[local_date]["tipSatang"] += int(booking.get("tipAmountSatang", 0))
        daily[local_date]["bookingCount"] += 1

    grouped_services_by_booking: dict[
        str, dict[tuple[str, str], dict[str, object]]
    ] = defaultdict(dict)
    for snapshot in line_snapshots:
        line = snapshot.to_dict() or {}
        booking_id = str(line.get("bookingDocId", ""))
        service = line.get("serviceSnapshot")
        if booking_id not in bookings or not isinstance(service, dict):
            continue
        service_id = str(service.get("serviceId", "unknown"))
        variant_id = str(service.get("variantId", "unknown"))
        key = (service_id, variant_id)
        group = grouped_services_by_booking[booking_id].setdefault(
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

    services: dict[tuple[str, str], dict[str, object]] = {}
    for booking_id, groups in grouped_services_by_booking.items():
        ordered_groups = sorted(groups.items(), key=lambda item: item[0])
        discount_shares = _allocate_discount(
            ordered_groups, int(bookings[booking_id].get("discountAmountSatang", 0))
        )
        for key, group in ordered_groups:
            aggregate = services.setdefault(
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
            aggregate["sessionCount"] = int(aggregate["sessionCount"]) + 1
            participants = group["participantIds"]
            aggregate["participantCount"] = int(aggregate["participantCount"]) + (
                len(participants) if isinstance(participants, set) else 0
            )
            aggregate["grossServiceSatang"] = int(aggregate["grossServiceSatang"]) + gross
            aggregate["discountAllocatedSatang"] = int(
                aggregate["discountAllocatedSatang"]
            ) + discount
            aggregate["netServiceSatang"] = int(aggregate["netServiceSatang"]) + gross - discount

    therapist_rows: dict[str, dict[str, object]] = {}
    for settlement in complete_settlements.values():
        for allocation in settlement.get("allocations") or []:
            if not isinstance(allocation, dict) or not allocation.get("therapistId"):
                continue
            therapist_id = str(allocation["therapistId"])
            row = therapist_rows.setdefault(
                therapist_id,
                {
                    "therapistId": therapist_id,
                    "therapistName": allocation.get("therapistName") or therapist_id,
                    "serviceCount": 0,
                    "durationMinutes": 0,
                    "therapistPaySatang": 0,
                    "tipSatang": 0,
                    "services": {},
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
            service_name = str(
                allocation.get("serviceNameTh") or allocation.get("serviceNameEn") or "—"
            )
            row_services = row["services"]
            if isinstance(row_services, dict):
                service_row = row_services.setdefault(
                    service_name,
                    {
                        "serviceName": service_name,
                        "count": 0,
                        "durationMinutes": 0,
                        "therapistPaySatang": 0,
                        "tipSatang": 0,
                    },
                )
                if isinstance(service_row, dict):
                    service_row["count"] = int(service_row["count"]) + 1
                    service_row["durationMinutes"] = int(
                        service_row["durationMinutes"]
                    ) + int(allocation.get("durationMinutes", 0))
                    service_row["therapistPaySatang"] = int(
                        service_row["therapistPaySatang"]
                    ) + int(allocation.get("therapistPaySatang", 0))
                    service_row["tipSatang"] = int(service_row["tipSatang"]) + int(
                        allocation.get("tipShareSatang", 0)
                    )

    scheduled_hours: dict[str, int] = defaultdict(int)
    actual_hours: dict[str, int] = defaultdict(int)
    for booking_id in eligible_ids:
        booking = bookings[booking_id]
        local_time = str(booking.get("localStartTime", ""))
        if len(local_time) >= 2:
            scheduled_hours[local_time[:2]] += 1
        started_at = booking.get("serviceStartedAt")
        if isinstance(started_at, datetime):
            actual_hours[started_at.astimezone(BANGKOK).strftime("%H")] += 1

    therapist_items = []
    for row in therapist_rows.values():
        services_map = row.pop("services")
        therapist_items.append(
            {
                **row,
                "services": sorted(
                    dict(services_map).values(),
                    key=lambda item: (-int(item["count"]), str(item["serviceName"])),
                ),
            }
        )

    return {
        "dateFrom": date_from,
        "dateTo": date_to,
        "timezone": "Asia/Bangkok",
        "summary": {
            "bookingCount": len(booking_snapshots),
            "servicedBookingCount": len(eligible_ids),
            "serviceRevenueSatang": service_revenue,
            "tipSatang": tips,
            "earnedGrossSatang": service_revenue + tips,
            "verifiedCollectedSatang": verified_collected,
            "historicalRecordedGrossSatang": historical_recorded_gross,
            "outstandingSatang": outstanding,
            "therapistPaySatang": therapist_pay,
            "therapistTipSatang": therapist_tip,
            "shopServiceSatang": shop_service,
            "shopTipSatang": shop_tip,
            "shopTotalSatang": shop_service + shop_tip,
            "settlementPendingCount": len(eligible_ids) - len(complete_settlements),
            "negativeShopServiceCount": sum(
                bool(item.get("negativeShopServiceAmount"))
                for item in complete_settlements.values()
            ),
        },
        "daily": [{"localDate": key, **daily[key]} for key in sorted(daily)],
        "services": sorted(
            services.values(),
            key=lambda item: (-int(item["sessionCount"]), -int(item["netServiceSatang"])),
        ),
        "therapists": sorted(
            therapist_items,
            key=lambda item: (-int(item["therapistPaySatang"]), str(item["therapistName"])),
        ),
        "peakHours": [
            {
                "hour": hour,
                "scheduledCount": scheduled_hours.get(hour, 0),
                "actualCount": actual_hours.get(hour, 0),
            }
            for hour in sorted(set(scheduled_hours) | set(actual_hours))
        ],
    }


def _insight_filters(
    *,
    source: str | None,
    admin_entry_mode: str | None,
    booking_status: str | None,
    payment_status: str | None,
    service_id: str | None,
    variant_id: str | None,
    therapist_id: str | None,
    settlement_state: str | None,
    has_discount: bool | None,
    has_tip: bool | None,
    hour_from: int | None,
    hour_to: int | None,
) -> InsightFilters:
    if hour_from is not None and hour_to is not None and hour_to < hour_from:
        raise ValidationDomainError("Insight end hour cannot be before start hour")
    return InsightFilters(
        source=source,
        admin_entry_mode=admin_entry_mode,
        booking_status=booking_status,
        payment_status=payment_status,
        service_id=service_id,
        variant_id=variant_id,
        therapist_id=therapist_id,
        settlement_state=settlement_state,  # type: ignore[arg-type]
        has_discount=has_discount,
        has_tip=has_tip,
        hour_from=hour_from,
        hour_to=hour_to,
    )


def _load_insight_payload(
    *,
    client: firestore.Client,
    date_from: str,
    date_to: str,
    branch_id: str,
    filters: InsightFilters,
    view: InsightView,
    page: int,
    page_size: int,
) -> dict[str, object]:
    _validate_date_range(date_from, date_to)
    booking_snapshots = list(
        client.collection("bookings")
        .where("branchId", "==", branch_id)
        .where("localDate", ">=", date_from)
        .where("localDate", "<=", date_to)
        .stream()
    )
    bookings = {snapshot.id: snapshot.to_dict() or {} for snapshot in booking_snapshots}
    booking_ids = list(bookings)
    line_snapshots = _related_documents(client, "booking_line_items", booking_ids)
    settlement_snapshots = (
        list(
            client.get_all(
                [client.collection("service_settlements").document(item) for item in booking_ids]
            )
        )
        if booking_ids
        else []
    )
    payload = build_insight_payload(
        bookings=bookings,
        lines=[snapshot.to_dict() or {} for snapshot in line_snapshots],
        settlements={
            snapshot.id: snapshot.to_dict() or {}
            for snapshot in settlement_snapshots
            if snapshot.exists
        },
        filters=filters,
        view=view,
        page=page,
        page_size=page_size,
    )
    return {
        "dateFrom": date_from,
        "dateTo": date_to,
        "timezone": "Asia/Bangkok",
        **payload,
    }


@router.get("/analytics/insight")
def analytics_insight(
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    date_from: Annotated[str, Query(alias="dateFrom")],
    date_to: Annotated[str, Query(alias="dateTo")],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
    view: Literal["BOOKINGS", "REVENUE", "SERVICES", "THERAPISTS"] = "BOOKINGS",
    source: Literal["GUEST_WEB", "LINE_CUSTOMER", "ADMIN_WEB"] | None = None,
    admin_entry_mode: Annotated[
        Literal["WALK_IN", "STAFF_ASSISTED", "HISTORICAL_RECORD"] | None,
        Query(alias="adminEntryMode"),
    ] = None,
    booking_status: Annotated[
        Literal["COMPLETED", "RECORDED"] | None, Query(alias="bookingStatus")
    ] = None,
    payment_status: Annotated[str | None, Query(alias="paymentStatus", max_length=40)] = None,
    service_id: Annotated[str | None, Query(alias="serviceId", max_length=160)] = None,
    variant_id: Annotated[str | None, Query(alias="variantId", max_length=160)] = None,
    therapist_id: Annotated[str | None, Query(alias="therapistId", max_length=160)] = None,
    settlement_state: Annotated[
        Literal["ALLOCATED", "PENDING", "STALE"] | None,
        Query(alias="settlementState"),
    ] = None,
    has_discount: Annotated[bool | None, Query(alias="hasDiscount")] = None,
    has_tip: Annotated[bool | None, Query(alias="hasTip")] = None,
    hour_from: Annotated[int | None, Query(alias="hourFrom", ge=0, le=23)] = None,
    hour_to: Annotated[int | None, Query(alias="hourTo", ge=0, le=23)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 50,
) -> dict[str, object]:
    _require_admin(actor)
    filters = _insight_filters(
        source=source,
        admin_entry_mode=admin_entry_mode,
        booking_status=booking_status,
        payment_status=payment_status,
        service_id=service_id,
        variant_id=variant_id,
        therapist_id=therapist_id,
        settlement_state=settlement_state,
        has_discount=has_discount,
        has_tip=has_tip,
        hour_from=hour_from,
        hour_to=hour_to,
    )
    return _load_insight_payload(
        client=client,
        date_from=date_from,
        date_to=date_to,
        branch_id=branch_id,
        filters=filters,
        view=view,
        page=page,
        page_size=page_size,
    )


INSIGHT_CSV_FIELDS: dict[InsightView, tuple[str, ...]] = {
    "BOOKINGS": (
        "bookingId",
        "localDate",
        "localStartTime",
        "status",
        "source",
        "adminEntryMode",
        "serviceNamesTh",
        "serviceNamesEn",
        "pax",
        "subtotalAmountSatang",
        "discountAmountSatang",
        "netServiceAmountSatang",
        "tipAmountSatang",
        "grossAmountSatang",
        "paymentStatus",
        "paidAmountSatang",
        "outstandingAmountSatang",
        "settlementState",
        "therapistNames",
        "therapistPaySatang",
        "therapistTipSatang",
        "shopTotalSatang",
    ),
    "REVENUE": (
        "localDate",
        "bookingCount",
        "netServiceAmountSatang",
        "tipAmountSatang",
        "grossAmountSatang",
        "paidAmountSatang",
        "outstandingAmountSatang",
        "therapistPaySatang",
        "therapistTipSatang",
        "shopTotalSatang",
    ),
    "SERVICES": (
        "serviceId",
        "variantId",
        "serviceNameTh",
        "serviceNameEn",
        "durationMinutes",
        "sessionCount",
        "participantCount",
        "grossServiceSatang",
        "discountAllocatedSatang",
        "netServiceSatang",
    ),
    "THERAPISTS": (
        "therapistId",
        "therapistName",
        "serviceCount",
        "durationMinutes",
        "therapistPaySatang",
        "tipSatang",
    ),
}


@router.post("/analytics/insight:export")
def export_analytics_insight(
    request: InsightExportInput,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> Response:
    _require_admin(actor)
    filters = _insight_filters(
        source=request.source,
        admin_entry_mode=request.admin_entry_mode,
        booking_status=request.booking_status,
        payment_status=request.payment_status,
        service_id=request.service_id,
        variant_id=request.variant_id,
        therapist_id=request.therapist_id,
        settlement_state=request.settlement_state,
        has_discount=request.has_discount,
        has_tip=request.has_tip,
        hour_from=request.hour_from,
        hour_to=request.hour_to,
    )
    payload = _load_insight_payload(
        client=client,
        date_from=request.date_from,
        date_to=request.date_to,
        branch_id=request.branch_id,
        filters=filters,
        view=request.view,
        page=1,
        page_size=5_000,
    )
    items = payload["items"]
    rows = items if isinstance(items, list) else []
    fields = INSIGHT_CSV_FIELDS[request.view]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in rows:
        if not isinstance(item, dict):
            continue
        writer.writerow(
            {
                key: " | ".join(str(value) for value in item.get(key, []))
                if isinstance(item.get(key), list)
                else item.get(key)
                for key in fields
            }
        )
    client.collection("audit_events").document().set(
        {
            "eventType": "ANALYTICS_CSV_EXPORTED",
            "actorId": actor["uid"],
            "actorType": "ADMIN_USER",
            "branchId": request.branch_id,
            "view": request.view,
            "dateFrom": request.date_from,
            "dateTo": request.date_to,
            "filters": request.model_dump(
                by_alias=True,
                exclude={"date_from", "date_to", "branch_id", "view"},
                exclude_none=True,
            ),
            "recordCount": len(rows),
            "createdAt": datetime.now(UTC),
        }
    )
    filename = (
        f"spa49-insight-{request.view.lower()}-{request.date_from}-{request.date_to}.csv"
    )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
