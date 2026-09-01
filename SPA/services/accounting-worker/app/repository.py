from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import GoogleAPICallError
from google.cloud.firestore_v1 import AsyncClient, AsyncTransaction
from google.cloud.firestore_v1.async_transaction import async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter

from app.contracts import ExportProjection
from app.processor import DeliveryOutcome, DeliveryState
from app.settings import Settings


class ExportRepositoryError(Exception):
    pass


class ExportNotEligible(ExportRepositoryError):
    pass


class ExportAlreadyFinal(ExportNotEligible):
    pass


@dataclass(frozen=True, slots=True)
class ClaimedExport:
    projection: ExportProjection
    lease_owner: str
    attempt_number: int
    run_id: str | None
    reconcile_only: bool


async def _one(transaction: AsyncTransaction, reference: Any) -> Any:
    return await reference.get(transaction=transaction)


def _projection(export_id: str, data: dict[str, Any]) -> ExportProjection:
    try:
        return ExportProjection.model_validate(
            {
                "export_id": export_id,
                "payment_id": data["paymentId"],
                "booking_public_id": data["bookingPublicId"],
                "accounting_date": data["accountingDate"],
                "external_reference": data["externalReference"],
                "external_document_id": data["externalDocumentId"],
                "payment_source": data["paymentSource"],
                "currency": data["currency"],
                "service_amount_satang": data["serviceAmountSatang"],
                "subtotal_amount_satang": data.get(
                    "subtotalAmountSatang", data["serviceAmountSatang"]
                ),
                "discount_amount_satang": data.get("discountAmountSatang", 0),
                "discount_reason": data.get("discountReason"),
                "tip_amount_satang": data["tipAmountSatang"],
                "gross_amount_satang": data["grossAmountSatang"],
                "service_lines": data["serviceLines"],
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ExportRepositoryError("Accounting export snapshot is invalid") from error


class FirestoreExportRepository:
    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        if settings.resolved_firestore_database != settings.expected_firestore_database:
            raise ExportRepositoryError("Firestore database does not match environment")
        self._settings = settings
        self._client = client or AsyncClient(
            project=settings.gcp_project_id,
            database=settings.resolved_firestore_database,
        )

    async def claim(self, export_id: str, now: datetime | None = None) -> ClaimedExport:
        claimed_at = now or datetime.now(UTC)
        lease_owner = uuid4().hex
        reference = self._client.collection("accounting_exports").document(export_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> ClaimedExport:
            snapshot = await _one(transaction, reference)
            if not snapshot.exists:
                raise ExportNotEligible("Accounting export does not exist")
            data = snapshot.to_dict() or {}
            if data.get("purpose") != "CUSTOMER_SALE":
                raise ExportNotEligible("Accounting export purpose is unsupported")
            current_status = data.get("status")
            if current_status in {"SYNCED", "CANCELLED"}:
                raise ExportAlreadyFinal(f"Accounting export is {current_status}")
            lease_expires_at = data.get("leaseExpiresAt")
            processing_lease_expired = (
                current_status == "PROCESSING"
                and isinstance(lease_expires_at, datetime)
                and lease_expires_at <= claimed_at
            )
            if current_status not in {
                "READY",
                "RETRYABLE",
                "ENQUEUED",
                "RECONCILE_REQUIRED",
            } and not processing_lease_expired:
                raise ExportNotEligible(f"Accounting export is {current_status}")
            next_attempt_at = data.get("nextAttemptAt")
            if (
                current_status == "RETRYABLE"
                and isinstance(next_attempt_at, datetime)
                and next_attempt_at > claimed_at
            ):
                raise ExportNotEligible("Accounting export retry is not due")
            projection = _projection(export_id, data)
            attempt_number = int(data.get("attemptCount", 0)) + 1
            transaction.update(
                reference,
                {
                    "status": "PROCESSING",
                    "leaseOwner": lease_owner,
                    "leaseExpiresAt": claimed_at
                    + timedelta(seconds=self._settings.export_lease_seconds),
                    "attemptCount": attempt_number,
                    "lastAttemptAt": claimed_at,
                    "updatedAt": claimed_at,
                },
            )
            return ClaimedExport(
                projection=projection,
                lease_owner=lease_owner,
                attempt_number=attempt_number,
                run_id=(str(data["activeRunId"]) if data.get("activeRunId") else None),
                reconcile_only=(
                    data.get("deliveryMode") == "RECONCILE"
                    or current_status == "RECONCILE_REQUIRED"
                ),
            )

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise ExportRepositoryError("Accounting export store is unavailable") from error

    async def complete(
        self,
        claimed: ClaimedExport,
        outcome: DeliveryOutcome,
        now: datetime | None = None,
    ) -> None:
        completed_at = now or datetime.now(UTC)
        reference = self._client.collection("accounting_exports").document(
            claimed.projection.export_id
        )

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            snapshot = await _one(transaction, reference)
            data = snapshot.to_dict() or {}
            if (
                not snapshot.exists
                or data.get("status") != "PROCESSING"
                or data.get("leaseOwner") != claimed.lease_owner
            ):
                raise ExportNotEligible("Accounting export lease changed")
            run_ref = None
            run_snapshot = None
            if claimed.run_id:
                run_ref = self._client.collection("accounting_sync_runs").document(
                    claimed.run_id
                )
                run_snapshot = await _one(transaction, run_ref)
            attempt_count = int(data.get("attemptCount", 1))
            values: dict[str, Any] = {
                "status": outcome.state,
                "safeErrorCode": outcome.safe_error_code,
                "leaseOwner": None,
                "leaseExpiresAt": None,
                "activeRunId": None,
                "deliveryMode": None,
                "updatedAt": completed_at,
            }
            if outcome.state is DeliveryState.SYNCED:
                values.update(
                    {
                        "flowAccountRecordId": outcome.provider_record_id,
                        "flowAccountDocumentId": outcome.provider_document_id,
                        "flowAccountDocumentSerial": outcome.provider_document_serial,
                        "flowAccountDocumentUrl": self._document_url(
                            outcome.provider_document_id
                        ),
                        "syncedAt": completed_at,
                        "nextAttemptAt": None,
                    }
                )
            elif outcome.state is DeliveryState.RETRYABLE:
                delay_minutes = min(60, 2 ** min(attempt_count, 5))
                values["nextAttemptAt"] = completed_at + timedelta(minutes=delay_minutes)
            else:
                values["nextAttemptAt"] = None
            transaction.update(reference, values)
            transaction.create(
                self._client.collection("accounting_sync_attempts").document(uuid4().hex),
                {
                    "exportId": claimed.projection.export_id,
                    "runId": claimed.run_id,
                    "attemptNumber": claimed.attempt_number,
                    "leaseOwner": claimed.lease_owner,
                    "operation": outcome.operation
                    or (
                        "RECONCILE_CASH_INVOICE"
                        if claimed.reconcile_only
                        else "CREATE_CASH_INVOICE_WITH_PAYMENT"
                    ),
                    "payloadDigest": outcome.payload_digest,
                    "latencyMs": outcome.latency_ms,
                    "result": outcome.state,
                    "safeErrorCode": outcome.safe_error_code,
                    "providerRecordId": outcome.provider_record_id,
                    "providerDocumentId": outcome.provider_document_id,
                    "createdAt": completed_at,
                    "expiresAt": completed_at + timedelta(days=90),
                },
            )
            transaction.create(
                self._client.collection("audit_events").document(uuid4().hex),
                {
                    "eventType": "FLOWACCOUNT_EXPORT_DELIVERY",
                    "actorType": "SERVICE",
                    "actorId": "accounting-worker",
                    "paymentId": claimed.projection.payment_id,
                    "accountingExportId": claimed.projection.export_id,
                    "result": outcome.state,
                    "safeErrorCode": outcome.safe_error_code,
                    "occurredAt": completed_at,
                    "createdAt": completed_at,
                    "retentionUntil": completed_at + timedelta(days=365 * 7),
                },
            )
            if outcome.state is not DeliveryState.SYNCED:
                alert_id = (
                    f"accounting-{claimed.projection.export_id}-"
                    f"{claimed.attempt_number}"
                )
                transaction.create(
                    self._client.collection("notification_outbox").document(alert_id),
                    {
                        "eventId": alert_id,
                        "eventType": "ACCOUNTING_OPERATIONAL_ALERT",
                        "aggregateType": "ACCOUNTING_EXPORT",
                        "aggregateId": claimed.projection.export_id,
                        "runId": claimed.run_id,
                        "environment": self._settings.environment,
                        "result": outcome.state,
                        "safeErrorCode": outcome.safe_error_code,
                        "adminUrl": self._settings.admin_accounting_url,
                        "state": "PENDING",
                        "attemptCount": 0,
                        "createdAt": completed_at,
                        "updatedAt": completed_at,
                        "expiresAt": completed_at + timedelta(days=90),
                    },
                )
            if run_ref is not None and run_snapshot is not None and run_snapshot.exists:
                run = run_snapshot.to_dict() or {}
                processed = int(run.get("processedCount", 0)) + 1
                synced = int(run.get("syncedCount", 0))
                failed = int(run.get("failedCount", 0))
                review = int(run.get("reviewCount", 0))
                if outcome.state is DeliveryState.SYNCED:
                    synced += 1
                elif outcome.state is DeliveryState.RETRYABLE:
                    failed += 1
                else:
                    review += 1
                enqueued = int(run.get("enqueuedCount", 0))
                run_values: dict[str, Any] = {
                    "processedCount": processed,
                    "syncedCount": synced,
                    "failedCount": failed,
                    "reviewCount": review,
                    "updatedAt": completed_at,
                }
                if enqueued and processed >= enqueued:
                    run_values["status"] = (
                        "PARTIAL_FAILURE" if failed or review else "COMPLETED"
                    )
                    run_values["completedAt"] = completed_at
                transaction.update(run_ref, run_values)

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise ExportRepositoryError("Accounting export result store is unavailable") from error

    async def due_export_ids(self, now: datetime | None = None) -> tuple[str, ...]:
        due_at = now or datetime.now(UTC)
        ids: list[str] = []
        try:
            for state in ("READY", "RETRYABLE"):
                query = (
                    self._client.collection("accounting_exports")
                    .where(filter=FieldFilter("status", "==", state))
                    .limit(self._settings.nightly_batch_size)
                )
                async for snapshot in query.stream():
                    data = snapshot.to_dict() or {}
                    next_attempt_at = data.get("nextAttemptAt")
                    if not isinstance(next_attempt_at, datetime) or next_attempt_at <= due_at:
                        ids.append(snapshot.id)
                        if len(ids) >= self._settings.nightly_batch_size:
                            return tuple(ids)
        except GoogleAPICallError as error:
            raise ExportRepositoryError("Accounting export queue is unavailable") from error
        return tuple(ids)

    def _document_url(self, document_id: str | None) -> str | None:
        template = self._settings.document_url_template
        if not document_id or not template:
            return None
        from urllib.parse import urlparse

        url = template.replace("{documentId}", document_id)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = any(
            host == rule or (rule.startswith("*.") and host.endswith(rule[1:]))
            for rule in self._settings.allowed_document_hosts
        )
        return url if parsed.scheme == "https" and allowed else None

    async def create_nightly_run(
        self,
        *,
        accounting_date: date,
        cutoff_at: datetime,
        requested_by: str,
    ) -> tuple[str, bool]:
        run_id = f"nightly_{accounting_date.isoformat()}"
        reference = self._client.collection("accounting_sync_runs").document(run_id)
        now = datetime.now(UTC)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> bool:
            snapshot = await _one(transaction, reference)
            if snapshot.exists:
                return False
            transaction.create(
                reference,
                {
                    "trigger": "SCHEDULED",
                    "runKey": f"NIGHTLY:{accounting_date.isoformat()}",
                    "accountingDate": accounting_date.isoformat(),
                    "cutoffAt": cutoff_at,
                    "requestedBy": requested_by,
                    "status": "PENDING",
                    "selectedCount": 0,
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
            return True

        return run_id, await run(self._client.transaction())

    async def run_export_ids(self, run_id: str) -> tuple[str, ...]:
        reference = self._client.collection("accounting_sync_runs").document(run_id)
        snapshot = await reference.get()
        if not snapshot.exists:
            raise ExportRepositoryError("Accounting sync run does not exist")
        run = snapshot.to_dict() or {}
        explicit = run.get("exportIds")
        if isinstance(explicit, list):
            return tuple(str(value) for value in explicit[:100] if value)
        cutoff = run.get("cutoffAt")
        if not isinstance(cutoff, datetime):
            raise ExportRepositoryError("Accounting sync run cutoff is invalid")
        query = (
            self._client.collection("accounting_exports")
            .where(filter=FieldFilter("purpose", "==", "CUSTOMER_SALE"))
            .where(
                filter=FieldFilter(
                    "status",
                    "in",
                    ["READY", "RETRYABLE", "RECONCILE_REQUIRED"],
                )
            )
            .where(filter=FieldFilter("paidAt", "<=", cutoff))
            .order_by("paidAt")
        )
        result: list[str] = []
        async for export in query.stream():
            data = export.to_dict() or {}
            retry_at = data.get("nextAttemptAt")
            retry_due = not isinstance(retry_at, datetime) or retry_at <= datetime.now(UTC)
            if data.get("status") in {"READY", "RECONCILE_REQUIRED"} or (
                data.get("status") == "RETRYABLE" and retry_due
            ):
                result.append(export.id)
                if len(result) >= self._settings.nightly_batch_size:
                    break
        return tuple(result)

    async def start_enqueuing(self, run_id: str) -> None:
        reference = self._client.collection("accounting_sync_runs").document(run_id)
        snapshot = await reference.get()
        if not snapshot.exists:
            raise ExportRepositoryError("Accounting sync run does not exist")
        data = snapshot.to_dict() or {}
        if data.get("status") in {"COMPLETED", "PARTIAL_FAILURE"}:
            return
        await reference.update(
            {"status": "ENQUEUING", "updatedAt": datetime.now(UTC)}
        )

    async def is_scheduled_run(self, run_id: str) -> bool:
        snapshot = await self._client.collection("accounting_sync_runs").document(
            run_id
        ).get()
        if not snapshot.exists:
            raise ExportRepositoryError("Accounting sync run does not exist")
        return (snapshot.to_dict() or {}).get("trigger") == "SCHEDULED"

    async def continue_enqueuing(self, run_id: str, *, selected_count: int) -> None:
        reference = self._client.collection("accounting_sync_runs").document(run_id)
        snapshot = await reference.get()
        if not snapshot.exists:
            raise ExportRepositoryError("Accounting sync run does not exist")
        current = snapshot.to_dict() or {}
        await reference.update(
            {
                "selectedCount": int(current.get("selectedCount", 0))
                + selected_count,
                "status": "ENQUEUING",
                "updatedAt": datetime.now(UTC),
            }
        )

    async def prepare_enqueue(self, export_id: str, run_id: str) -> int:
        reference = self._client.collection("accounting_exports").document(export_id)
        run_ref = self._client.collection("accounting_sync_runs").document(run_id)
        now = datetime.now(UTC)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> int:
            export_snapshot = await _one(transaction, reference)
            run_snapshot = await _one(transaction, run_ref)
            if not export_snapshot.exists or not run_snapshot.exists:
                raise ExportNotEligible("Accounting export or run does not exist")
            data = export_snapshot.to_dict() or {}
            current = data.get("status")
            if (
                current in {"ENQUEUE_PENDING", "ENQUEUED"}
                and data.get("activeRunId") == run_id
            ):
                return int(data.get("enqueueGeneration", 0))
            operation = (run_snapshot.to_dict() or {}).get("operation", "AUTO")
            allowed = (
                current == "RECONCILE_REQUIRED"
                if operation == "RECONCILE"
                else current == "RETRYABLE"
                if operation == "RETRY"
                else current in {"READY", "RETRYABLE"}
                if operation == "SYNC"
                else current in {"READY", "RETRYABLE", "RECONCILE_REQUIRED"}
            )
            if not allowed:
                raise ExportNotEligible(
                    f"Accounting export is not eligible for {operation} from {current}"
                )
            next_attempt_at = data.get("nextAttemptAt")
            if (
                current == "RETRYABLE"
                and isinstance(next_attempt_at, datetime)
                and next_attempt_at > now
            ):
                raise ExportNotEligible("Accounting export retry is not due")
            generation = int(data.get("enqueueGeneration", 0)) + 1
            transaction.update(
                reference,
                {
                    "status": "ENQUEUE_PENDING",
                    "activeRunId": run_id,
                    "deliveryMode": (
                        "RECONCILE"
                        if current == "RECONCILE_REQUIRED"
                        else "CREATE"
                    ),
                    "enqueueGeneration": generation,
                    "updatedAt": now,
                },
            )
            return generation

        return await run(self._client.transaction())

    async def confirm_enqueued(
        self, export_id: str, run_id: str, generation: int
    ) -> bool:
        reference = self._client.collection("accounting_exports").document(export_id)
        run_ref = self._client.collection("accounting_sync_runs").document(run_id)
        now = datetime.now(UTC)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> bool:
            export_snapshot = await _one(transaction, reference)
            run_snapshot = await _one(transaction, run_ref)
            if not export_snapshot.exists or not run_snapshot.exists:
                raise ExportNotEligible("Accounting export or run does not exist")
            data = export_snapshot.to_dict() or {}
            if data.get("status") == "ENQUEUED" and int(
                data.get("enqueueGeneration", 0)
            ) == generation:
                if data.get("activeRunId") != run_id:
                    raise ExportNotEligible("Accounting export belongs to another run")
                return False
            current = data.get("status")
            if current != "ENQUEUE_PENDING" or data.get("activeRunId") != run_id:
                raise ExportNotEligible(f"Accounting export is {current}")
            if int(data.get("enqueueGeneration", 0)) != generation:
                raise ExportNotEligible("Accounting export enqueue generation changed")
            transaction.update(
                reference,
                {
                    "status": "ENQUEUED",
                    "enqueuedAt": now,
                    "updatedAt": now,
                },
            )
            transaction.update(
                run_ref,
                {
                    "enqueuedCount": int(
                        (run_snapshot.to_dict() or {}).get("enqueuedCount", 0)
                    )
                    + 1,
                    "updatedAt": now,
                },
            )
            return True

        return await run(self._client.transaction())

    async def finish_enqueuing(
        self, run_id: str, *, selected_count: int, accumulate_selection: bool = False
    ) -> int:
        now = datetime.now(UTC)
        reference = self._client.collection("accounting_sync_runs").document(run_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> int:
            snapshot = await _one(transaction, reference)
            if not snapshot.exists:
                raise ExportRepositoryError("Accounting sync run does not exist")
            current = snapshot.to_dict() or {}
            enqueued_count = int(current.get("enqueuedCount", 0))
            processed_count = int(current.get("processedCount", 0))
            failed_count = int(current.get("failedCount", 0))
            review_count = int(current.get("reviewCount", 0))
            finished = enqueued_count == 0 or processed_count >= enqueued_count
            values: dict[str, Any] = {
                "selectedCount": (
                    int(current.get("selectedCount", 0)) + selected_count
                    if accumulate_selection
                    else selected_count
                ),
                "enqueuedCount": enqueued_count,
                "status": (
                    "PARTIAL_FAILURE"
                    if finished and (failed_count or review_count)
                    else "COMPLETED"
                    if finished
                    else "RUNNING"
                ),
                "updatedAt": now,
            }
            if finished:
                values["completedAt"] = now
            transaction.update(reference, values)
            return enqueued_count

        return await run(self._client.transaction())
