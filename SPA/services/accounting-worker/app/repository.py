from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


@dataclass(frozen=True, slots=True)
class ClaimedExport:
    projection: ExportProjection
    lease_owner: str


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
            lease_expires_at = data.get("leaseExpiresAt")
            processing_lease_expired = (
                current_status == "PROCESSING"
                and isinstance(lease_expires_at, datetime)
                and lease_expires_at <= claimed_at
            )
            if current_status not in {"READY", "RETRYABLE"} and not processing_lease_expired:
                raise ExportNotEligible(f"Accounting export is {current_status}")
            next_attempt_at = data.get("nextAttemptAt")
            if (
                current_status == "RETRYABLE"
                and isinstance(next_attempt_at, datetime)
                and next_attempt_at > claimed_at
            ):
                raise ExportNotEligible("Accounting export retry is not due")
            projection = _projection(export_id, data)
            transaction.update(
                reference,
                {
                    "status": "PROCESSING",
                    "leaseOwner": lease_owner,
                    "leaseExpiresAt": claimed_at
                    + timedelta(seconds=self._settings.export_lease_seconds),
                    "attemptCount": int(data.get("attemptCount", 0)) + 1,
                    "lastAttemptAt": claimed_at,
                    "updatedAt": claimed_at,
                },
            )
            return ClaimedExport(projection=projection, lease_owner=lease_owner)

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
            attempt_count = int(data.get("attemptCount", 1))
            values: dict[str, Any] = {
                "status": outcome.state,
                "safeErrorCode": outcome.safe_error_code,
                "leaseOwner": None,
                "leaseExpiresAt": None,
                "updatedAt": completed_at,
            }
            if outcome.state is DeliveryState.SYNCED:
                values.update(
                    {
                        "flowAccountRecordId": outcome.provider_record_id,
                        "flowAccountDocumentId": outcome.provider_document_id,
                        "flowAccountDocumentSerial": outcome.provider_document_serial,
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
                },
            )

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
