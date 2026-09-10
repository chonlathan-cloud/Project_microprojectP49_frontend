import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.errors import (
    AccountingExportAlreadySynced,
    AccountingExportNotEligible,
    AccountingExportPurposeUnsupported,
    FinancialConflict,
    IdempotencyConflict,
    NotFoundDomainError,
    PersistenceUnavailable,
    ValidationDomainError,
)
from app.core.settings import Settings
from app.core.types import CashSettlementStatus, PaymentSource
from app.domains.accounting.factory import build_accounting_export
from app.infrastructure.firestore_payments import (
    _export_data,
    _new_payment,
    _payment_data,
    _payment_id,
    _service_lines,
    _with_tip,
)

BANGKOK = ZoneInfo("Asia/Bangkok")
CLAIMABLE_SYNC_STATES = {"READY", "RETRYABLE"}
ATTENTION_STATES = {"RECONCILE_REQUIRED", "REVIEW_REQUIRED"}


def _cursor_fingerprint(filters: dict[str, object]) -> str:
    payload = json.dumps(filters, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _encode_cursor(paid_at: datetime, export_id: str, fingerprint: str) -> str:
    payload = json.dumps(
        {
            "paidAt": paid_at.isoformat(),
            "exportId": export_id,
            "fingerprint": fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(token: str, fingerprint: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        value = json.loads(raw)
        paid_at = datetime.fromisoformat(str(value["paidAt"]))
        export_id = str(value["exportId"])
        if value.get("fingerprint") != fingerprint or paid_at.tzinfo is None or not export_id:
            raise ValueError
        return paid_at, export_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidationDomainError("Invalid accounting page token") from error


def _local_boundary(value: date) -> datetime:
    return datetime.combine(value, time.min, BANGKOK).astimezone(UTC)


class FirestoreAccountingRepository:
    def __init__(self, settings: Settings, client: firestore.Client | None = None) -> None:
        self._settings = settings
        self._client = client or firestore.Client(
            project=settings.gcp_project_id,
            database=settings.firestore_database,
        )

    def _allowlisted_document_url(self, value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = any(
            host == rule or (rule.startswith("*.") and host.endswith(rule[1:]))
            for rule in self._settings.configured_flowaccount_document_hosts
        )
        return value if parsed.scheme == "https" and allowed else None

    def _read_model(self, snapshot: Any) -> dict[str, Any]:
        export = snapshot.to_dict() or {}
        payment_snapshot = self._client.collection("payments").document(
            str(export.get("paymentId", ""))
        ).get()
        payment = payment_snapshot.to_dict() if payment_snapshot.exists else {}
        booking_snapshot = self._client.collection("bookings").document(
            str(export.get("bookingDocId", ""))
        ).get()
        booking = booking_snapshot.to_dict() if booking_snapshot.exists else {}
        contact = booking.get("contact") if isinstance(booking.get("contact"), dict) else {}
        service_lines = payment.get("serviceLines")
        if not isinstance(service_lines, list):
            service_lines = (
                export.get("serviceLines")
                if isinstance(export.get("serviceLines"), list)
                else []
            )
        names = [
            str(line.get("name"))
            for line in service_lines
            if isinstance(line, dict) and line.get("name")
        ]
        return {
            "exportId": snapshot.id,
            "paymentId": export.get("paymentId"),
            "bookingId": export.get("bookingPublicId"),
            "bookingDocId": export.get("bookingDocId"),
            "branchId": export.get("branchId"),
            "serviceAt": booking.get("startAt"),
            "adminEntryMode": booking.get("adminEntryMode"),
            "historicalFinancialRecord": bool(booking.get("historicalFinancialRecord")),
            "customerName": booking.get("customerName") or "—",
            "customerPhoneMasked": contact.get("phoneMasked") or "—",
            "serviceSummary": ", ".join(names) or "—",
            "pax": booking.get("pax") or len(booking.get("participants") or []) or 1,
            "paymentStatus": payment.get("status") or "PAID",
            "paymentSource": export.get("paymentSource"),
            "paidAt": export.get("paidAt"),
            "providerReferenceId": payment.get("providerResourceId"),
            "serviceAmountSatang": int(export.get("serviceAmountSatang", 0)),
            "tipAmountSatang": int(export.get("tipAmountSatang", 0)),
            "grossAmountSatang": int(export.get("grossAmountSatang", 0)),
            "currency": export.get("currency", "THB"),
            "projectName": export.get("projectName", "Spa 49"),
            "exportStatus": export.get("status"),
            "flowAccountDocumentId": export.get("flowAccountDocumentId"),
            "flowAccountDocumentSerial": export.get("flowAccountDocumentSerial"),
            "flowAccountDocumentUrl": self._allowlisted_document_url(
                export.get("flowAccountDocumentUrl")
            ),
            "cashSettlementStatus": payment.get("cashSettlementStatus", "NOT_APPLICABLE"),
            "cashDepositId": payment.get("cashDepositId"),
            "attemptCount": int(export.get("attemptCount", 0)),
            "lastErrorCode": export.get("safeErrorCode") or export.get("lastErrorCode"),
            "accountingDate": export.get("accountingDate"),
            "updatedAt": export.get("updatedAt"),
            "syncedAt": export.get("syncedAt"),
        }

    def list_payments(
        self,
        *,
        branch_id: str,
        date_from: date,
        date_to: date,
        export_status: str | None,
        payment_source: str | None,
        cash_settlement_status: str | None,
        requires_attention: bool,
        search: str,
        page_size: int,
        page_token: str | None,
    ) -> dict[str, Any]:
        filters = {
            "branchId": branch_id,
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "exportStatus": export_status,
            "paymentSource": payment_source,
            "cashSettlementStatus": cash_settlement_status,
            "requiresAttention": requires_attention,
            "search": search.casefold().strip(),
        }
        fingerprint = _cursor_fingerprint(filters)
        query = (
            self._client.collection("accounting_exports")
            .where(filter=FieldFilter("branchId", "==", branch_id))
            .where(filter=FieldFilter("paidAt", ">=", _local_boundary(date_from)))
            .where(filter=FieldFilter("paidAt", "<", _local_boundary(date_to)))
            .order_by("paidAt", direction=firestore.Query.DESCENDING)
            .order_by("__name__", direction=firestore.Query.DESCENDING)
        )
        if page_token:
            paid_at, export_id = _decode_cursor(page_token, fingerprint)
            cursor = self._client.collection("accounting_exports").document(export_id).get()
            cursor_data = cursor.to_dict() if cursor.exists else {}
            if cursor_data.get("paidAt") != paid_at or cursor_data.get("branchId") != branch_id:
                raise ValidationDomainError("Accounting page token is stale")
            query = query.start_after(cursor)

        items: list[dict[str, Any]] = []
        last_snapshot = None
        scanned = 0
        try:
            for snapshot in query.limit(300).stream():
                scanned += 1
                last_snapshot = snapshot
                model = self._read_model(snapshot)
                state = str(model.get("exportStatus", ""))
                if export_status and state != export_status:
                    continue
                if requires_attention and state not in ATTENTION_STATES:
                    continue
                if payment_source and model.get("paymentSource") != payment_source:
                    continue
                if (
                    cash_settlement_status
                    and model.get("cashSettlementStatus") != cash_settlement_status
                ):
                    continue
                needle = search.casefold().strip()
                if needle:
                    haystack = " ".join(
                        str(model.get(key, ""))
                        for key in ("bookingId", "customerName", "customerPhoneMasked")
                    ).casefold()
                    if needle not in haystack:
                        continue
                items.append(model)
                if len(items) >= page_size:
                    break
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Accounting payment list is unavailable") from error

        next_page_token = None
        if last_snapshot is not None and (len(items) >= page_size or scanned >= 300):
            paid_at = (last_snapshot.to_dict() or {}).get("paidAt")
            if isinstance(paid_at, datetime):
                next_page_token = _encode_cursor(paid_at, last_snapshot.id, fingerprint)
        summary = {
            "scope": "CURRENT_PAGE",
            "paidGrossSatang": sum(item["grossAmountSatang"] for item in items),
            "beamGrossSatang": sum(
                item["grossAmountSatang"] for item in items if item["paymentSource"] == "BEAM"
            ),
            "cashGrossSatang": sum(
                item["grossAmountSatang"] for item in items if item["paymentSource"] == "CASH"
            ),
            "bankTransferGrossSatang": sum(
                item["grossAmountSatang"]
                for item in items
                if item["paymentSource"] == "BANK_TRANSFER"
            ),
            "serviceAmountSatang": sum(item["serviceAmountSatang"] for item in items),
            "tipAmountSatang": sum(item["tipAmountSatang"] for item in items),
            "readyCount": sum(item["exportStatus"] == "READY" for item in items),
            "syncedCount": sum(item["exportStatus"] == "SYNCED" for item in items),
            "attentionCount": sum(item["exportStatus"] in ATTENTION_STATES for item in items),
        }
        return {"items": items, "nextPageToken": next_page_token, "summary": summary}

    def list_pending_historical(self, *, branch_id: str, limit: int = 100) -> dict[str, Any]:
        try:
            snapshots = list(
                self._client.collection("bookings")
                .where(filter=FieldFilter("branchId", "==", branch_id))
                .stream()
            )
        except GoogleAPICallError as error:
            raise PersistenceUnavailable(
                "Historical accounting queue is unavailable"
            ) from error
        items: list[dict[str, Any]] = []
        for snapshot in snapshots:
            booking = snapshot.to_dict() or {}
            if (
                booking.get("status") != "RECORDED"
                or booking.get("adminEntryMode") != "HISTORICAL_RECORD"
                or booking.get("historicalFinancialRecord") is not True
                or booking.get("financiallyExcluded") is not False
                or booking.get("paymentStatus") != "UNAVAILABLE"
            ):
                continue
            contact = booking.get("contact")
            contact = contact if isinstance(contact, dict) else {}
            service_names = booking.get("serviceNamesTh")
            if not isinstance(service_names, list) or not service_names:
                service_names = [
                    booking.get("serviceNameTh")
                    or booking.get("serviceNameEn")
                    or booking.get("serviceName")
                    or "—"
                ]
            start_at = booking.get("startAt")
            end_at = booking.get("endAt")
            items.append(
                {
                    "bookingId": booking.get("publicBookingId", snapshot.id),
                    "serviceAt": start_at,
                    "suggestedPaidAt": end_at or start_at,
                    "customerName": booking.get("customerName") or "—",
                    "customerPhoneMasked": contact.get("phoneMasked") or "—",
                    "serviceSummary": ", ".join(str(value) for value in service_names),
                    "pax": int(booking.get("pax", 1)),
                    "serviceAmountSatang": int(
                        booking.get("estimatedAmountSatang", 0)
                    ),
                    "tipAmountSatang": int(booking.get("tipAmountSatang", 0)),
                    "grossAmountSatang": int(
                        booking.get(
                            "grossAmountSatang",
                            int(booking.get("estimatedAmountSatang", 0))
                            + int(booking.get("tipAmountSatang", 0)),
                        )
                    ),
                    "version": int(booking.get("version", 1)),
                }
            )
        items.sort(
            key=lambda item: (
                item.get("serviceAt")
                if isinstance(item.get("serviceAt"), datetime)
                else datetime.min.replace(tzinfo=UTC),
                str(item.get("bookingId", "")),
            ),
            reverse=True,
        )
        return {"items": items[:limit], "total": len(items)}

    def record_historical_payment(
        self,
        *,
        booking_public_id: str,
        branch_ids: tuple[str, ...],
        actor_uid: str,
        payment_source: PaymentSource,
        paid_at: datetime,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if payment_source not in {PaymentSource.CASH, PaymentSource.BANK_TRANSFER}:
            raise ValidationDomainError("Historical payment source is invalid")
        if paid_at.tzinfo is None or paid_at.utcoffset() is None:
            raise ValidationDomainError("Historical paid time must include a timezone offset")
        now = datetime.now(UTC)
        if paid_at.astimezone(UTC) > now:
            raise ValidationDomainError("Historical paid time cannot be in the future")

        matches = list(
            self._client.collection("bookings")
            .where(filter=FieldFilter("publicBookingId", "==", booking_public_id))
            .limit(2)
            .stream()
        )
        if len(matches) != 1:
            raise NotFoundDomainError("Historical Booking not found")
        booking_ref = matches[0].reference
        line_snapshots = list(
            self._client.collection("booking_line_items")
            .where(filter=FieldFilter("bookingDocId", "==", booking_ref.id))
            .stream()
        )
        payment_ref = self._client.collection("payments").document(
            _payment_id(booking_ref.id)
        )
        idem_ref = self._client.collection("idempotency_records").document(
            hashlib.sha256(
                f"historical-payment:{actor_uid}:{booking_public_id}:{idempotency_key}".encode()
            ).hexdigest()
        )
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "bookingId": booking_public_id,
                    "paymentSource": payment_source.value,
                    "paidAt": paid_at.isoformat(),
                    "expectedVersion": expected_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        @firestore.transactional
        def commit(transaction: firestore.Transaction) -> dict[str, Any]:
            idem_snapshot = idem_ref.get(transaction=transaction)
            booking_snapshot = booking_ref.get(transaction=transaction)
            payment_snapshot = payment_ref.get(transaction=transaction)
            if idem_snapshot.exists:
                idem = idem_snapshot.to_dict() or {}
                if idem.get("requestDigest") != request_digest:
                    raise IdempotencyConflict(
                        "Historical payment idempotency key conflicts"
                    )
                response = idem.get("response")
                if not isinstance(response, dict):
                    raise FinancialConflict("Historical payment replay is invalid")
                return response
            if not booking_snapshot.exists:
                raise NotFoundDomainError("Historical Booking not found")
            booking = booking_snapshot.to_dict() or {}
            if str(booking.get("branchId", "")) not in branch_ids:
                raise NotFoundDomainError("Historical Booking not found")
            if (
                booking.get("status") != "RECORDED"
                or booking.get("adminEntryMode") != "HISTORICAL_RECORD"
                or booking.get("historicalFinancialRecord") is not True
                or booking.get("financiallyExcluded") is not False
                or booking.get("paymentStatus") != "UNAVAILABLE"
            ):
                raise FinancialConflict(
                    "Historical Booking is not awaiting payment classification"
                )
            if int(booking.get("version", 1)) != expected_version:
                raise FinancialConflict("Historical Booking changed; reload and try again")
            if payment_snapshot.exists:
                raise FinancialConflict("Historical Booking already has a Payment")

            lines = _service_lines(line_snapshots)
            payment = _new_payment(booking_ref.id, booking, lines)
            tip_amount = int(booking.get("tipAmountSatang", 0))
            payment = _with_tip(payment, tip_amount)
            expected_gross = booking.get("grossAmountSatang")
            if expected_gross is not None and int(expected_gross) != (
                payment.amounts.gross_amount_satang
            ):
                raise FinancialConflict("Historical Booking gross amount is inconsistent")
            payment = payment.mark_paid(
                source=payment_source,
                paid_at=paid_at,
                cash_received_by=(
                    actor_uid if payment_source is PaymentSource.CASH else None
                ),
                manual_received_by=(
                    actor_uid
                    if payment_source is PaymentSource.BANK_TRANSFER
                    else None
                ),
            )
            if payment_source is PaymentSource.CASH:
                payment = replace(
                    payment, cash_settlement_status=CashSettlementStatus.REVIEW
                )
            export = build_accounting_export(payment)
            export_ref = self._client.collection("accounting_exports").document(
                export.export_id
            )
            export_snapshot = export_ref.get(transaction=transaction)
            if export_snapshot.exists:
                raise FinancialConflict("Historical Booking already has an accounting export")

            next_version = int(booking.get("version", 1)) + 1
            response = {
                "bookingId": booking_public_id,
                "paymentId": payment.payment_id,
                "exportId": export.export_id,
                "paymentStatus": "PAID",
                "paymentSource": payment_source.value,
                "paidAt": paid_at,
                "grossAmountSatang": payment.amounts.gross_amount_satang,
                "version": next_version,
            }
            transaction.create(
                payment_ref, {**_payment_data(payment, now), "createdAt": now}
            )
            transaction.create(export_ref, _export_data(export, now))
            transaction.update(
                booking_ref,
                {
                    "paymentStatus": "PAID",
                    "paidAmountSatang": payment.amounts.gross_amount_satang,
                    "amountDueSatang": 0,
                    "paymentUpdatedAt": paid_at,
                    "version": next_version,
                    "updatedAt": now,
                },
            )
            transaction.create(
                self._client.collection("audit_events").document(),
                {
                    "eventType": "HISTORICAL_PAYMENT_CLASSIFIED",
                    "actorType": "ADMIN_USER",
                    "actorId": actor_uid,
                    "branchId": booking.get("branchId"),
                    "bookingDocId": booking_ref.id,
                    "publicBookingId": booking_public_id,
                    "paymentId": payment.payment_id,
                    "paymentSource": payment_source.value,
                    "paidAt": paid_at,
                    "grossAmountSatang": payment.amounts.gross_amount_satang,
                    "occurredAt": now,
                    "createdAt": now,
                },
            )
            transaction.create(
                idem_ref,
                {
                    "scope": "HISTORICAL_PAYMENT_CLASSIFICATION",
                    "actorId": actor_uid,
                    "requestDigest": request_digest,
                    "response": response,
                    "createdAt": now,
                    "expiresAt": now
                    + timedelta(hours=self._settings.idempotency_ttl_hours),
                },
            )
            return response

        try:
            return commit(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable(
                "Historical payment store is unavailable"
            ) from error

    def detail(self, payment_id: str, *, branch_ids: tuple[str, ...]) -> dict[str, Any]:
        exports = list(
            self._client.collection("accounting_exports")
            .where(filter=FieldFilter("paymentId", "==", payment_id))
            .limit(2)
            .stream()
        )
        if len(exports) != 1:
            raise NotFoundDomainError("Payment accounting export not found")
        model = self._read_model(exports[0])
        if model.get("branchId") not in branch_ids:
            raise NotFoundDomainError("Payment accounting export not found")
        attempts = [
            {"attemptId": item.id, **(item.to_dict() or {})}
            for item in self._client.collection("accounting_sync_attempts")
            .where(filter=FieldFilter("exportId", "==", exports[0].id))
            .limit(50)
            .stream()
        ]
        attempts.sort(
            key=lambda item: item.get("createdAt") or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return {"payment": model, "attempts": attempts}

    def eligible_export_ids(
        self, *, branch_ids: tuple[str, ...], operation: str, limit: int = 100
    ) -> tuple[str, ...]:
        required_state = "RECONCILE_REQUIRED" if operation == "RECONCILE" else None
        ids: list[str] = []
        for branch_id in branch_ids:
            query = (
                self._client.collection("accounting_exports")
                .where(filter=FieldFilter("branchId", "==", branch_id))
                .limit(limit * 3)
            )
            for snapshot in query.stream():
                data = snapshot.to_dict() or {}
                state = data.get("status")
                if data.get("purpose") != "CUSTOMER_SALE":
                    continue
                if required_state and state != required_state:
                    continue
                if not required_state and state not in CLAIMABLE_SYNC_STATES:
                    continue
                ids.append(snapshot.id)
                if len(ids) >= limit:
                    return tuple(ids)
        return tuple(ids)

    def create_run(
        self,
        *,
        actor_uid: str,
        branch_ids: tuple[str, ...],
        export_ids: tuple[str, ...],
        operation: str,
        idempotency_key: str,
    ) -> tuple[str, bool]:
        if not export_ids or len(export_ids) > 100:
            raise ValidationDomainError("Select between 1 and 100 accounting exports")
        request_digest = hashlib.sha256(
            json.dumps(
                {"exportIds": sorted(export_ids), "operation": operation},
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        idem_id = hashlib.sha256(
            f"accounting-run:{actor_uid}:{idempotency_key}".encode()
        ).hexdigest()
        idem_ref = self._client.collection("idempotency_records").document(idem_id)
        export_refs = [
            self._client.collection("accounting_exports").document(export_id)
            for export_id in export_ids
        ]
        run_id = uuid4().hex
        run_ref = self._client.collection("accounting_sync_runs").document(run_id)
        now = datetime.now(UTC)
        transaction = self._client.transaction()

        @firestore.transactional
        def commit(transaction: firestore.Transaction) -> tuple[str, bool]:
            idem_snapshot = idem_ref.get(transaction=transaction)
            if idem_snapshot.exists:
                idem = idem_snapshot.to_dict() or {}
                if idem.get("requestDigest") != request_digest:
                    raise IdempotencyConflict("Accounting run idempotency key conflicts")
                return str(idem["runId"]), False
            snapshots = [ref.get(transaction=transaction) for ref in export_refs]
            for snapshot in snapshots:
                if not snapshot.exists:
                    raise NotFoundDomainError("Accounting export not found")
                data = snapshot.to_dict() or {}
                if data.get("purpose") != "CUSTOMER_SALE":
                    raise AccountingExportPurposeUnsupported(
                        "Only customer-sale exports can be synchronized"
                    )
                if data.get("branchId") not in branch_ids:
                    raise AccountingExportNotEligible("Accounting export branch is not allowed")
                state = data.get("status")
                if state == "SYNCED":
                    raise AccountingExportAlreadySynced("Accounting export is already synced")
                if operation == "RECONCILE":
                    allowed = state == "RECONCILE_REQUIRED"
                elif operation == "RETRY":
                    allowed = state == "RETRYABLE"
                else:
                    allowed = state in CLAIMABLE_SYNC_STATES
                if not allowed:
                    raise AccountingExportNotEligible(
                        f"Accounting export is not eligible from {state}"
                    )
            transaction.create(
                run_ref,
                {
                    "trigger": "MANUAL",
                    "runKey": f"MANUAL:{run_id}",
                    "operation": operation,
                    "requestedBy": actor_uid,
                    "branchIds": list(branch_ids),
                    "exportIds": list(export_ids),
                    "status": "PENDING",
                    "selectedCount": len(export_ids),
                    "enqueuedCount": 0,
                    "processedCount": 0,
                    "syncedCount": 0,
                    "failedCount": 0,
                    "reviewCount": 0,
                    "createdAt": now,
                    "updatedAt": now,
                    "expiresAt": now + timedelta(days=365),
                },
            )
            transaction.create(
                idem_ref,
                {
                    "scope": "ACCOUNTING_SYNC_RUN",
                    "actorId": actor_uid,
                    "requestDigest": request_digest,
                    "runId": run_id,
                    "createdAt": now,
                    "expiresAt": now
                    + timedelta(hours=self._settings.idempotency_ttl_hours),
                },
            )
            transaction.create(
                self._client.collection("audit_events").document(),
                {
                    "eventType": "ACCOUNTING_SYNC_RUN_REQUESTED",
                    "actorType": "ADMIN_USER",
                    "actorId": actor_uid,
                    "runId": run_id,
                    "operation": operation,
                    "selectedCount": len(export_ids),
                    "createdAt": now,
                    "retentionUntil": now + timedelta(days=365 * 7),
                },
            )
            return run_id, True

        try:
            return commit(transaction)
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Accounting sync run store is unavailable") from error

    def get_run(self, run_id: str, *, branch_ids: tuple[str, ...]) -> dict[str, Any]:
        snapshot = self._client.collection("accounting_sync_runs").document(run_id).get()
        if not snapshot.exists:
            raise NotFoundDomainError("Accounting sync run not found")
        data = snapshot.to_dict() or {}
        run_branches = data.get("branchIds")
        if isinstance(run_branches, list) and not set(run_branches).intersection(branch_ids):
            raise NotFoundDomainError("Accounting sync run not found")
        return {"runId": snapshot.id, **data}
