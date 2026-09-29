from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

from app.core.errors import (
    ConflictDomainError,
    HistoricalCorrectionRequired,
    IdempotencyConflict,
    NotFoundDomainError,
    ValidationDomainError,
)
from app.infrastructure.firestore_payments import _payment_id


@dataclass(frozen=True, slots=True)
class HistoricalVoidEligibility:
    eligible: bool
    reason_code: str | None
    payment_status: str
    export_status: str | None
    settlement_state: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reasonCode": self.reason_code,
            "paymentStatus": self.payment_status,
            "exportStatus": self.export_status,
            "settlementState": self.settlement_state,
        }


@dataclass(frozen=True, slots=True)
class _HistoricalVoidContext:
    booking: dict[str, Any]
    payment: dict[str, Any]
    export: dict[str, Any]
    settlement: dict[str, Any]
    payment_ref: Any
    export_ref: Any | None
    settlement_ref: Any
    allocation_guard: dict[str, Any]
    eligibility: HistoricalVoidEligibility


def _payout_covers_service_date(
    payout: dict[str, Any], *, therapist_ids: set[str], service_date: str
) -> bool:
    if str(payout.get("therapistId") or "") not in therapist_ids:
        return False
    allocations = payout.get("dailyAllocations")
    if isinstance(allocations, list):
        return any(
            isinstance(item, dict)
            and item.get("localDate") == service_date
            and int(item.get("amountSatang", 0)) != 0
            for item in allocations
        )
    return (
        str(payout.get("dateFrom") or "") <= service_date
        and str(payout.get("dateTo") or "") >= service_date
    )


class FirestoreHistoricalCorrectionRepository:
    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def _booking_snapshot(self, booking_public_id: str) -> Any:
        matches = list(
            self._client.collection("bookings")
            .where("publicBookingId", "==", booking_public_id)
            .limit(2)
            .stream()
        )
        if len(matches) != 1:
            raise NotFoundDomainError("Historical Booking not found")
        return matches[0]

    def _context(
        self,
        booking_ref: Any,
        *,
        branch_ids: tuple[str, ...],
        transaction: Any | None = None,
    ) -> _HistoricalVoidContext:
        booking_snapshot = booking_ref.get(transaction=transaction)
        if not booking_snapshot.exists:
            raise NotFoundDomainError("Historical Booking not found")
        booking = booking_snapshot.to_dict() or {}
        if str(booking.get("branchId") or "") not in branch_ids:
            raise NotFoundDomainError("Historical Booking not found")

        payment_ref = self._client.collection("payments").document(_payment_id(booking_ref.id))
        payment_snapshot = payment_ref.get(transaction=transaction)
        payment = payment_snapshot.to_dict() or {} if payment_snapshot.exists else {}

        export_snapshots = list(
            self._client.collection("accounting_exports")
            .where("bookingDocId", "==", booking_ref.id)
            .limit(2)
            .stream(transaction=transaction)
        )
        export_snapshot = export_snapshots[0] if len(export_snapshots) == 1 else None
        export = export_snapshot.to_dict() or {} if export_snapshot else {}
        export_ref = export_snapshot.reference if export_snapshot else None

        settlement_ref = self._client.collection("service_settlements").document(booking_ref.id)
        settlement_snapshot = settlement_ref.get(transaction=transaction)
        settlement = settlement_snapshot.to_dict() or {} if settlement_snapshot.exists else {}

        guard_ref = self._client.collection("cash_deposit_allocation_guards").document(
            payment_ref.id
        )
        guard_snapshot = guard_ref.get(transaction=transaction)
        allocation_guard = guard_snapshot.to_dict() or {} if guard_snapshot.exists else {}

        payout_locked = False
        if settlement:
            therapist_ids = {
                str(item.get("therapistId"))
                for item in settlement.get("allocations") or []
                if isinstance(item, dict) and item.get("therapistId")
            }
            service_date = str(settlement.get("serviceDate") or booking.get("localDate") or "")
            if therapist_ids and service_date:
                payouts = list(
                    self._client.collection("therapist_payouts")
                    .where("branchId", "==", booking.get("branchId"))
                    .stream(transaction=transaction)
                )
                payout_locked = any(
                    _payout_covers_service_date(
                        snapshot.to_dict() or {},
                        therapist_ids=therapist_ids,
                        service_date=service_date,
                    )
                    for snapshot in payouts
                )

        payment_status = str(booking.get("paymentStatus") or payment.get("status") or "")
        export_status = str(export.get("status") or "") or None
        settlement_state = str(settlement.get("state") or "") or None
        reason_code: str | None = None

        if (
            booking.get("status") != "RECORDED"
            or booking.get("adminEntryMode") != "HISTORICAL_RECORD"
            or booking.get("historicalFinancialRecord") is not True
            or booking.get("financiallyExcluded") is not False
        ):
            reason_code = "NOT_ACTIVE_HISTORICAL_RECORD"
        elif payment_status != "PAID" or payment.get("status") != "PAID":
            reason_code = "PAYMENT_NOT_PAID"
        elif len(export_snapshots) != 1:
            reason_code = "ACCOUNTING_EXPORT_INCONSISTENT"
        elif export_status != "READY":
            reason_code = (
                "ACCOUNTING_EXPORT_SYNCED"
                if export_status == "SYNCED"
                else "ACCOUNTING_EXPORT_IN_FLIGHT"
                if export_status in {"ENQUEUE_PENDING", "ENQUEUED", "PROCESSING"}
                else "ACCOUNTING_CORRECTION_REQUIRED"
            )
        elif int(export.get("attemptCount", 0)) > 0 or any(
            export.get(field)
            for field in (
                "flowAccountRecordId",
                "flowAccountDocumentId",
                "flowAccountDocumentSerial",
            )
        ):
            reason_code = "ACCOUNTING_EXPORT_ATTEMPTED"
        elif payment.get("paymentMethod") == "CASH" and (
            payment.get("cashSettlementStatus") != "UNSETTLED"
            or allocation_guard.get("active") is True
        ):
            reason_code = "CASH_SETTLEMENT_IN_PROGRESS"
        elif payout_locked:
            reason_code = "THERAPIST_COMPENSATION_PAID"

        return _HistoricalVoidContext(
            booking=booking,
            payment=payment,
            export=export,
            settlement=settlement,
            payment_ref=payment_ref,
            export_ref=export_ref,
            settlement_ref=settlement_ref,
            allocation_guard=allocation_guard,
            eligibility=HistoricalVoidEligibility(
                eligible=reason_code is None,
                reason_code=reason_code,
                payment_status=payment_status or "UNAVAILABLE",
                export_status=export_status,
                settlement_state=settlement_state,
            ),
        )

    def inspect(
        self, booking_public_id: str, *, branch_ids: tuple[str, ...]
    ) -> HistoricalVoidEligibility:
        snapshot = self._booking_snapshot(booking_public_id)
        return self._context(snapshot.reference, branch_ids=branch_ids).eligibility

    def void(
        self,
        booking_public_id: str,
        *,
        branch_ids: tuple[str, ...],
        actor_uid: str,
        expected_version: int,
        command_id: str,
        reason: str,
    ) -> dict[str, object]:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationDomainError("Historical void reason is required")
        booking_snapshot = self._booking_snapshot(booking_public_id)
        booking = booking_snapshot.to_dict() or {}
        if str(booking.get("branchId") or "") not in branch_ids:
            raise NotFoundDomainError("Historical Booking not found")
        booking_ref = booking_snapshot.reference
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "bookingId": booking_public_id,
                    "expectedVersion": expected_version,
                    "reason": normalized_reason,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        command_ref = self._client.collection("admin_commands").document(
            hashlib.sha256(command_id.encode()).hexdigest()
        )

        @firestore.transactional
        def commit(transaction: firestore.Transaction) -> dict[str, object]:
            command_snapshot = command_ref.get(transaction=transaction)
            if command_snapshot.exists:
                command = command_snapshot.to_dict() or {}
                if (
                    command.get("action") != "VOID_HISTORICAL"
                    or command.get("actorId") != actor_uid
                    or command.get("requestDigest") != request_digest
                ):
                    raise IdempotencyConflict(
                        "Command ID was already used with different historical correction data"
                    )
                response = command.get("response")
                if not isinstance(response, dict):
                    raise IdempotencyConflict("Historical correction replay is invalid")
                return response

            context = self._context(
                booking_ref,
                branch_ids=branch_ids,
                transaction=transaction,
            )
            current_version = int(context.booking.get("version", 1))
            if current_version != expected_version:
                raise ConflictDomainError("Historical Booking changed; reload before trying again")
            if not context.eligibility.eligible:
                raise HistoricalCorrectionRequired(
                    context.eligibility.reason_code
                    or "Historical Booking requires accounting correction"
                )
            if context.export_ref is None:
                raise HistoricalCorrectionRequired("ACCOUNTING_EXPORT_INCONSISTENT")

            now = datetime.now(UTC)
            next_version = current_version + 1
            payment_version = int(context.payment.get("version", 1)) + 1
            response: dict[str, object] = {
                "bookingId": booking_public_id,
                "status": "CANCELLED",
                "version": next_version,
                "paymentStatus": "VOIDED",
                "exportStatus": "CANCELLED",
                "financiallyExcluded": True,
            }

            transaction.update(
                booking_ref,
                {
                    "status": "CANCELLED",
                    "customerListBucket": "HISTORY",
                    "financiallyExcluded": True,
                    "paymentStatus": "VOIDED",
                    "paidAmountSatang": 0,
                    "amountDueSatang": 0,
                    "paymentUpdatedAt": now,
                    **({"financialSettlementStatus": "VOIDED"} if context.settlement else {}),
                    "cancellation": {
                        "reason": normalized_reason,
                        "cancelledAt": now,
                        "cancelledBy": actor_uid,
                        "kind": "HISTORICAL_FINANCIAL_VOID",
                    },
                    "historicalCorrection": {
                        "type": "VOID_BEFORE_ACCOUNTING_SYNC",
                        "reason": normalized_reason,
                        "correctedAt": now,
                        "correctedBy": actor_uid,
                    },
                    "version": next_version,
                    "updatedAt": now,
                },
            )
            transaction.update(
                context.payment_ref,
                {
                    "status": "VOIDED",
                    "paidAmountSatang": 0,
                    "cashSettlementStatus": "NOT_APPLICABLE",
                    "voidedAt": now,
                    "voidedBy": actor_uid,
                    "voidReason": normalized_reason,
                    "version": payment_version,
                    "updatedAt": now,
                },
            )
            transaction.update(
                context.export_ref,
                {
                    "status": "CANCELLED",
                    "cancelledAt": now,
                    "cancelledBy": actor_uid,
                    "cancelReason": normalized_reason,
                    "nextAttemptAt": None,
                    "updatedAt": now,
                },
            )
            if context.settlement:
                transaction.update(
                    context.settlement_ref,
                    {
                        "state": "VOIDED",
                        "voidedAt": now,
                        "voidedBy": actor_uid,
                        "voidReason": normalized_reason,
                        "version": int(context.settlement.get("version", 0)) + 1,
                        "updatedAt": now,
                    },
                )
            transaction.set(
                self._client.collection("audit_events").document(),
                {
                    "eventType": "HISTORICAL_FINANCIAL_RECORD_VOIDED",
                    "actorType": "ADMIN_USER",
                    "actorId": actor_uid,
                    "branchId": context.booking.get("branchId"),
                    "bookingDocId": booking_ref.id,
                    "publicBookingId": booking_public_id,
                    "paymentId": context.payment_ref.id,
                    "accountingExportId": context.export_ref.id,
                    "previousBookingStatus": context.booking.get("status"),
                    "newBookingStatus": "CANCELLED",
                    "bookingVersionBefore": current_version,
                    "bookingVersionAfter": next_version,
                    "previousPaymentStatus": context.payment.get("status"),
                    "newPaymentStatus": "VOIDED",
                    "previousExportStatus": context.export.get("status"),
                    "newExportStatus": "CANCELLED",
                    "previousSettlementState": (
                        context.settlement.get("state") if context.settlement else None
                    ),
                    "newSettlementState": "VOIDED" if context.settlement else None,
                    "grossAmountSatang": int(
                        context.payment.get(
                            "grossAmountSatang",
                            context.booking.get("grossAmountSatang", 0),
                        )
                    ),
                    "reason": normalized_reason,
                    "occurredAt": now,
                    "createdAt": now,
                },
            )
            transaction.set(
                command_ref,
                {
                    "action": "VOID_HISTORICAL",
                    "actorId": actor_uid,
                    "bookingDocId": booking_ref.id,
                    "requestDigest": request_digest,
                    "response": response,
                    "createdAt": now,
                },
            )
            return response

        return commit(self._client.transaction())
