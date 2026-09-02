import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import GoogleAPICallError
from google.cloud.firestore_v1 import AsyncClient, AsyncTransaction
from google.cloud.firestore_v1.async_transaction import async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter

from app.application.cash_deposits import CashAllocationRequest, PreparedCashDepositAttempt
from app.core.errors import (
    CashDepositEvidenceInvalid,
    CashDepositNotEligible,
    ConflictDomainError,
    FinancialConflict,
    IdempotencyConflict,
    NotFoundDomainError,
    PersistenceUnavailable,
)
from app.core.settings import Settings
from app.core.types import CashDepositStatus, CashSettlementStatus
from app.domains.identity.models import AdminPrincipal
from app.domains.payments.cash_deposits import (
    CashDepositChargeSnapshot,
    validate_cash_deposit_charge,
)
from app.infrastructure.firestore import firestore_client
from app.integrations.beam import BeamCharge


async def _one(transaction: AsyncTransaction, reference: Any) -> Any:
    return await reference.get(transaction=transaction)


def _idem_id(scope: str, actor_id: str, key: str) -> str:
    return hashlib.sha256(f"{scope}:{actor_id}:{key}".encode()).hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


class FirestoreCashDepositRepository:
    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        if settings.resolved_firestore_database != settings.expected_firestore_database:
            raise PersistenceUnavailable("Firestore database does not match runtime environment")
        self._settings = settings
        self._client = client or firestore_client(
            settings.gcp_project_id, settings.resolved_firestore_database
        )

    def _deposit_ref(self, deposit_id: str):
        return self._client.collection("cash_deposits").document(deposit_id)

    async def list_unsettled(self, *, branch_ids: tuple[str, ...], branch_id: str) -> list[dict]:
        if branch_id not in branch_ids:
            raise NotFoundDomainError("Cash payments not found")
        query = (
            self._client.collection("payments")
            .where(filter=FieldFilter("branchId", "==", branch_id))
            .where(filter=FieldFilter("paymentMethod", "==", "CASH"))
            .where(filter=FieldFilter("status", "==", "PAID"))
            .where(filter=FieldFilter("cashSettlementStatus", "==", "UNSETTLED"))
            .limit(200)
        )
        try:
            snapshots = [snapshot async for snapshot in query.stream()]
            result: list[dict] = []
            for snapshot in snapshots:
                payment = snapshot.to_dict() or {}
                booking_snapshot = (
                    await self._client.collection("bookings")
                    .document(str(payment.get("bookingDocId", "")))
                    .get()
                )
                booking = booking_snapshot.to_dict() if booking_snapshot.exists else {}
                result.append(
                    {
                        "paymentId": snapshot.id,
                        "bookingId": payment.get("bookingPublicId"),
                        "customerName": booking.get("customerName") or "—",
                        "paidAt": payment.get("paidAt"),
                        "grossAmountSatang": int(payment.get("grossAmountSatang", 0)),
                        "currency": payment.get("currency", "THB"),
                        "version": int(payment.get("version", 1)),
                        "cashReceivedBy": payment.get("cashReceivedBy"),
                    }
                )
            result.sort(
                key=lambda item: item.get("paidAt") or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )
            return result
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Unsettled cash list is unavailable") from error

    async def create_draft(
        self,
        *,
        principal: AdminPrincipal,
        branch_id: str,
        allocations: tuple[CashAllocationRequest, ...],
        expected_total_satang: int,
        idempotency_key: str,
        now: datetime,
    ) -> dict:
        if (
            not allocations
            or len(allocations) > 100
            or len({item.payment_id for item in allocations}) != len(allocations)
        ):
            raise CashDepositNotEligible("Select between 1 and 100 unique cash payments")
        if expected_total_satang <= 0:
            raise CashDepositNotEligible("Cash deposit total must be positive")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "branchId": branch_id,
                    "allocations": sorted(
                        (item.payment_id, item.expected_version) for item in allocations
                    ),
                    "total": expected_total_satang,
                },
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        idem_ref = self._client.collection("idempotency_records").document(
            _idem_id("CASH_DEPOSIT_CREATE", principal.uid, idempotency_key)
        )
        deposit_id = "dep_" + uuid4().hex[:24]
        deposit_ref = self._deposit_ref(deposit_id)
        payment_refs = [
            self._client.collection("payments").document(item.payment_id) for item in allocations
        ]
        guard_refs = [
            self._client.collection("cash_deposit_allocation_guards").document(item.payment_id)
            for item in allocations
        ]

        @async_transactional
        async def run(transaction: AsyncTransaction) -> str:
            idem = await _one(transaction, idem_ref)
            if idem.exists:
                data = idem.to_dict() or {}
                if data.get("requestDigest") != digest:
                    raise IdempotencyConflict("Cash deposit idempotency key conflicts")
                return str(data.get("depositId"))
            payment_snapshots = [await _one(transaction, ref) for ref in payment_refs]
            guard_snapshots = [await _one(transaction, ref) for ref in guard_refs]
            total = 0
            allocation_rows: list[dict[str, Any]] = []
            for request, snapshot, guard in zip(
                allocations, payment_snapshots, guard_snapshots, strict=True
            ):
                if not snapshot.exists:
                    raise CashDepositNotEligible("Cash payment no longer exists")
                data = snapshot.to_dict() or {}
                if (
                    data.get("branchId") != branch_id
                    or data.get("paymentMethod") != "CASH"
                    or data.get("status") != "PAID"
                    or data.get("cashSettlementStatus") != "UNSETTLED"
                ):
                    raise CashDepositNotEligible("Cash payment is no longer unsettled")
                if int(data.get("version", 1)) != request.expected_version:
                    raise ConflictDomainError("Cash payment version changed")
                if guard.exists and (guard.to_dict() or {}).get("active") is True:
                    raise CashDepositNotEligible("Cash payment is already allocated")
                amount = int(data.get("grossAmountSatang", 0))
                if amount <= 0 or data.get("currency", "THB") != "THB":
                    raise CashDepositNotEligible("Cash payment amount is invalid")
                total += amount
                allocation_rows.append(
                    {
                        "paymentId": snapshot.id,
                        "bookingId": data.get("bookingPublicId"),
                        "amountSatang": amount,
                        "paymentVersion": request.expected_version,
                    }
                )
            if total != expected_total_satang:
                raise FinancialConflict("Cash allocation sum does not match confirmed total")
            transaction.create(
                deposit_ref,
                {
                    "depositId": deposit_id,
                    "branchId": branch_id,
                    "status": CashDepositStatus.DRAFT.value,
                    "currency": "THB",
                    "totalAmountSatang": total,
                    "allocationCount": len(allocation_rows),
                    "allocations": allocation_rows,
                    "createdBy": principal.uid,
                    "version": 1,
                    "createdAt": now,
                    "updatedAt": now,
                    "retentionUntil": now + timedelta(days=365 * 7),
                },
            )
            for row, payment_ref, guard_ref, snapshot in zip(
                allocation_rows, payment_refs, guard_refs, payment_snapshots, strict=True
            ):
                payment = snapshot.to_dict() or {}
                transaction.set(
                    guard_ref,
                    {
                        "active": True,
                        "depositId": deposit_id,
                        "paymentId": payment_ref.id,
                        "updatedAt": now,
                    },
                )
                transaction.update(
                    payment_ref,
                    {
                        "cashSettlementStatus": CashSettlementStatus.DEPOSIT_PENDING.value,
                        "cashDepositId": deposit_id,
                        "version": int(payment.get("version", 1)) + 1,
                        "updatedAt": now,
                    },
                )
                transaction.create(
                    deposit_ref.collection("allocations").document(payment_ref.id),
                    {**row, "createdAt": now},
                )
            transaction.create(
                idem_ref,
                {
                    "scope": "CASH_DEPOSIT_CREATE",
                    "actorId": principal.uid,
                    "requestDigest": digest,
                    "depositId": deposit_id,
                    "createdAt": now,
                    "expiresAt": now + timedelta(hours=self._settings.idempotency_ttl_hours),
                },
            )
            transaction.create(
                self._client.collection("audit_events").document(),
                {
                    "eventType": "CASH_DEPOSIT_DRAFT_CREATED",
                    "actorType": "ADMIN_USER",
                    "actorId": principal.uid,
                    "depositId": deposit_id,
                    "branchId": branch_id,
                    "totalAmountSatang": total,
                    "createdAt": now,
                    "retentionUntil": now + timedelta(days=365 * 7),
                },
            )
            return deposit_id

        try:
            resolved = await run(self._client.transaction())
            return await self.get(resolved, branch_ids=principal.branch_ids)
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit draft store is unavailable") from error

    async def get(self, deposit_id: str, *, branch_ids: tuple[str, ...]) -> dict:
        try:
            snapshot = await self._deposit_ref(deposit_id).get()
            if not snapshot.exists:
                raise NotFoundDomainError("Cash deposit not found")
            data = snapshot.to_dict() or {}
            if data.get("branchId") not in branch_ids:
                raise NotFoundDomainError("Cash deposit not found")
            result = {"depositId": snapshot.id, **_clean(data)}
            attempt_id = data.get("activeAttemptId") or data.get("latestAttemptId")
            if isinstance(attempt_id, str) and attempt_id:
                attempt = (
                    await self._client.collection("cash_deposit_attempts")
                    .document(attempt_id)
                    .get()
                )
                if attempt.exists:
                    result["attempt"] = {"attemptId": attempt.id, **_clean(attempt.to_dict() or {})}
            return result
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit is unavailable") from error

    async def begin_evidence(
        self,
        *,
        deposit_id: str,
        principal: AdminPrincipal,
        evidence_id: str,
        object_name: str,
        content_type: str,
        size_bytes: int,
        sha256_hex: str,
        now: datetime,
    ) -> None:
        ref = self._deposit_ref(deposit_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            snapshot = await _one(transaction, ref)
            if not snapshot.exists:
                raise NotFoundDomainError("Cash deposit not found")
            data = snapshot.to_dict() or {}
            if data.get("branchId") not in principal.branch_ids or data.get("status") not in {
                CashDepositStatus.DRAFT.value,
                CashDepositStatus.EVIDENCE_UPLOADING.value,
            }:
                raise CashDepositNotEligible("Cash deposit cannot accept evidence")
            transaction.update(
                ref,
                {
                    "status": CashDepositStatus.EVIDENCE_UPLOADING.value,
                    "evidence": {
                        "evidenceId": evidence_id,
                        "objectName": object_name,
                        "contentType": content_type,
                        "sizeBytes": size_bytes,
                        "sha256": sha256_hex,
                        "status": "UPLOADING",
                        "authorizedBy": principal.uid,
                        "authorizedAt": now,
                    },
                    "version": int(data.get("version", 1)) + 1,
                    "updatedAt": now,
                },
            )

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash evidence state is unavailable") from error

    async def confirm_evidence(
        self, *, deposit_id: str, principal: AdminPrincipal, generation: int, now: datetime
    ) -> dict:
        ref = self._deposit_ref(deposit_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            snapshot = await _one(transaction, ref)
            if not snapshot.exists:
                raise NotFoundDomainError("Cash deposit not found")
            data = snapshot.to_dict() or {}
            evidence = data.get("evidence") or {}
            if data.get("branchId") not in principal.branch_ids:
                raise NotFoundDomainError("Cash deposit not found")
            if (
                evidence.get("status") == "READY"
                and int(evidence.get("generation", 0)) == generation
                and data.get("status")
                in {
                    CashDepositStatus.READY_FOR_QR.value,
                    CashDepositStatus.QR_CREATING.value,
                    CashDepositStatus.QR_ACTIVE.value,
                    CashDepositStatus.COMPLETED.value,
                    CashDepositStatus.REVIEW.value,
                }
            ):
                return
            if (
                data.get("status") != CashDepositStatus.EVIDENCE_UPLOADING.value
                or evidence.get("status") != "UPLOADING"
            ):
                raise CashDepositEvidenceInvalid("Cash evidence is not awaiting confirmation")
            transaction.update(
                ref,
                {
                    "status": CashDepositStatus.READY_FOR_QR.value,
                    "evidence.status": "READY",
                    "evidence.generation": generation,
                    "evidence.confirmedBy": principal.uid,
                    "evidence.confirmedAt": now,
                    "version": int(data.get("version", 1)) + 1,
                    "updatedAt": now,
                },
            )

        try:
            await run(self._client.transaction())
            return await self.get(deposit_id, branch_ids=principal.branch_ids)
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash evidence confirmation is unavailable") from error

    async def begin_attempt(
        self,
        *,
        deposit_id: str,
        principal: AdminPrincipal,
        expected_version: int,
        idempotency_key: str,
        now: datetime,
        expires_at: datetime,
    ) -> PreparedCashDepositAttempt:
        deposit_ref = self._deposit_ref(deposit_id)
        attempt_id = "cda_" + uuid4().hex[:24]
        attempt_ref = self._client.collection("cash_deposit_attempts").document(attempt_id)
        idem_ref = self._client.collection("idempotency_records").document(
            _idem_id("CASH_DEPOSIT_ATTEMPT", principal.uid, idempotency_key)
        )
        provider_reference = f"SPA-CASH-DEP-{deposit_id}-{attempt_id}"
        provider_idempotency = hashlib.sha256(f"cash-deposit:{attempt_id}".encode()).hexdigest()

        @async_transactional
        async def run(transaction: AsyncTransaction) -> PreparedCashDepositAttempt:
            idem = await _one(transaction, idem_ref)
            if idem.exists:
                stored = idem.to_dict() or {}
                existing = await _one(
                    transaction,
                    self._client.collection("cash_deposit_attempts").document(
                        str(stored.get("attemptId", ""))
                    ),
                )
                if not existing.exists or stored.get("depositId") != deposit_id:
                    raise IdempotencyConflict("Cash deposit attempt idempotency key conflicts")
                item = existing.to_dict() or {}
                return PreparedCashDepositAttempt(
                    deposit_id,
                    existing.id,
                    int(item["totalAmountSatang"]),
                    str(item["currency"]),
                    str(item["providerReferenceId"]),
                    str(item["providerIdempotencyKey"]),
                    item["expiresAt"],
                    True,
                )
            snapshot = await _one(transaction, deposit_ref)
            if not snapshot.exists:
                raise NotFoundDomainError("Cash deposit not found")
            data = snapshot.to_dict() or {}
            if (
                data.get("branchId") not in principal.branch_ids
                or int(data.get("version", 1)) != expected_version
            ):
                raise ConflictDomainError("Cash deposit version changed")
            if data.get("status") not in {
                CashDepositStatus.READY_FOR_QR.value,
                CashDepositStatus.FAILED.value,
                CashDepositStatus.EXPIRED.value,
            }:
                raise CashDepositNotEligible("Cash deposit is not ready for a new QR")
            transaction.create(
                attempt_ref,
                {
                    "depositId": deposit_id,
                    "branchId": data.get("branchId"),
                    "status": "CREATING",
                    "currency": data.get("currency", "THB"),
                    "totalAmountSatang": data.get("totalAmountSatang"),
                    "providerReferenceId": provider_reference,
                    "providerIdempotencyKey": provider_idempotency,
                    "createdBy": principal.uid,
                    "createdAt": now,
                    "expiresAt": expires_at,
                    "version": 1,
                    "updatedAt": now,
                },
            )
            transaction.update(
                deposit_ref,
                {
                    "status": CashDepositStatus.QR_CREATING.value,
                    "activeAttemptId": attempt_id,
                    "latestAttemptId": attempt_id,
                    "version": expected_version + 1,
                    "updatedAt": now,
                },
            )
            transaction.create(
                idem_ref,
                {
                    "scope": "CASH_DEPOSIT_ATTEMPT",
                    "actorId": principal.uid,
                    "depositId": deposit_id,
                    "attemptId": attempt_id,
                    "createdAt": now,
                    "expiresAt": now + timedelta(hours=self._settings.idempotency_ttl_hours),
                },
            )
            return PreparedCashDepositAttempt(
                deposit_id,
                attempt_id,
                int(data["totalAmountSatang"]),
                str(data.get("currency", "THB")),
                provider_reference,
                provider_idempotency,
                expires_at,
            )

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit attempt store is unavailable") from error

    async def activate_attempt(
        self,
        prepared: PreparedCashDepositAttempt,
        *,
        provider_charge_id: str,
        provider_expires_at: datetime | None,
        now: datetime,
    ) -> None:
        deposit_ref = self._deposit_ref(prepared.deposit_id)
        attempt_ref = self._client.collection("cash_deposit_attempts").document(prepared.attempt_id)
        link_ref = self._client.collection("beam_charge_links").document(provider_charge_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            deposit_snapshot = await _one(transaction, deposit_ref)
            attempt_snapshot = await _one(transaction, attempt_ref)
            link_snapshot = await _one(transaction, link_ref)
            if not deposit_snapshot.exists or not attempt_snapshot.exists:
                raise FinancialConflict("Cash deposit attempt state is incomplete")
            deposit = deposit_snapshot.to_dict() or {}
            attempt = attempt_snapshot.to_dict() or {}
            if (
                link_snapshot.exists
                or attempt.get("status") != "CREATING"
                or deposit.get("activeAttemptId") != prepared.attempt_id
            ):
                raise FinancialConflict("Cash deposit Beam charge is already linked")
            transaction.create(
                link_ref,
                {
                    "purpose": "CASH_DEPOSIT",
                    "cashDepositId": prepared.deposit_id,
                    "attemptId": prepared.attempt_id,
                    "providerReferenceId": prepared.provider_reference_id,
                    "createdAt": now,
                },
            )
            transaction.update(
                attempt_ref,
                {
                    "status": "ACTIVE",
                    "providerChargeId": provider_charge_id,
                    "expiresAt": provider_expires_at or prepared.requested_expires_at,
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )
            transaction.update(
                deposit_ref,
                {
                    "status": CashDepositStatus.QR_ACTIVE.value,
                    "version": int(deposit.get("version", 1)) + 1,
                    "updatedAt": now,
                },
            )

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit Beam link is unavailable") from error

    async def _mark_attempt(
        self, attempt_id: str, *, attempt_status: str, deposit_status: str, now: datetime
    ) -> None:
        attempt_ref = self._client.collection("cash_deposit_attempts").document(attempt_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            attempt_snapshot = await _one(transaction, attempt_ref)
            if not attempt_snapshot.exists:
                return
            attempt = attempt_snapshot.to_dict() or {}
            deposit_ref = self._deposit_ref(str(attempt.get("depositId", "")))
            deposit_snapshot = await _one(transaction, deposit_ref)
            if not deposit_snapshot.exists:
                return
            deposit = deposit_snapshot.to_dict() or {}
            transaction.update(
                attempt_ref,
                {
                    "status": attempt_status,
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )
            transaction.update(
                deposit_ref,
                {
                    "status": deposit_status,
                    "activeAttemptId": None,
                    "version": int(deposit.get("version", 1)) + 1,
                    "updatedAt": now,
                },
            )

        await run(self._client.transaction())

    async def mark_attempt_unknown(self, attempt_id: str, *, now: datetime) -> None:
        await self._mark_attempt(
            attempt_id,
            attempt_status="CREATE_UNKNOWN",
            deposit_status=CashDepositStatus.REVIEW.value,
            now=now,
        )

    async def mark_attempt_failed(self, attempt_id: str, *, now: datetime) -> None:
        await self._mark_attempt(
            attempt_id,
            attempt_status="FAILED",
            deposit_status=CashDepositStatus.FAILED.value,
            now=now,
        )

    async def cash_deposit_for_charge(self, charge_id: str) -> bool:
        try:
            snapshot = await self._client.collection("beam_charge_links").document(charge_id).get()
            return snapshot.exists and (snapshot.to_dict() or {}).get("purpose") == "CASH_DEPOSIT"
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit charge lookup is unavailable") from error

    async def settle_charge(
        self,
        *,
        event_id: str,
        event_type: str,
        charge: BeamCharge,
        expected_merchant_id: str,
        now: datetime,
    ) -> bool:
        link_ref = self._client.collection("beam_charge_links").document(charge.charge_id)
        event_ref = self._client.collection("payment_webhook_events").document(event_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> bool:
            link_snapshot = await _one(transaction, link_ref)
            event_snapshot = await _one(transaction, event_ref)
            if (
                not link_snapshot.exists
                or (link_snapshot.to_dict() or {}).get("purpose") != "CASH_DEPOSIT"
            ):
                return False
            if (
                event_snapshot.exists
                and (event_snapshot.to_dict() or {}).get("status") == "PROCESSED"
            ):
                return True
            link = link_snapshot.to_dict() or {}
            attempt_ref = self._client.collection("cash_deposit_attempts").document(
                str(link.get("attemptId", ""))
            )
            deposit_ref = self._deposit_ref(str(link.get("cashDepositId", "")))
            attempt_snapshot = await _one(transaction, attempt_ref)
            deposit_snapshot = await _one(transaction, deposit_ref)
            if not attempt_snapshot.exists or not deposit_snapshot.exists:
                raise FinancialConflict("Cash deposit settlement state is incomplete")
            attempt = attempt_snapshot.to_dict() or {}
            deposit = deposit_snapshot.to_dict() or {}
            early_event_data = {
                "provider": "BEAM",
                "purpose": "CASH_DEPOSIT",
                "eventType": event_type,
                "providerResourceId": charge.charge_id,
                "cashDepositId": deposit_ref.id,
                "status": "PROCESSED",
                "receivedAt": (
                    (event_snapshot.to_dict() or {}).get("receivedAt", now)
                    if event_snapshot.exists
                    else now
                ),
                "processedAt": now,
                "updatedAt": now,
            }
            if deposit.get("status") == CashDepositStatus.COMPLETED.value:
                if event_snapshot.exists:
                    transaction.update(event_ref, early_event_data)
                else:
                    transaction.create(event_ref, early_event_data)
                return True
            if charge.status not in {
                "SUCCEEDED",
                "FAILED",
                "EXPIRED",
                "CANCELED",
                "CANCELLED",
            }:
                transaction.update(
                    attempt_ref,
                    {
                        "lastReconciledAt": now,
                        "providerStatus": charge.status,
                        "updatedAt": now,
                    },
                )
                if event_snapshot.exists:
                    transaction.update(event_ref, early_event_data)
                else:
                    transaction.create(event_ref, early_event_data)
                return True
            allocations = deposit.get("allocations")
            if not isinstance(allocations, list) or not allocations:
                raise FinancialConflict("Cash deposit allocations are missing")
            payment_refs = [
                self._client.collection("payments").document(str(row.get("paymentId", "")))
                for row in allocations
            ]
            guard_refs = [
                self._client.collection("cash_deposit_allocation_guards").document(ref.id)
                for ref in payment_refs
            ]
            payment_snapshots = [await _one(transaction, ref) for ref in payment_refs]
            guard_snapshots = [await _one(transaction, ref) for ref in guard_refs]
            final_status = CashDepositStatus.FAILED.value
            attempt_status = "FAILED"
            review_reason = None
            if charge.status == "SUCCEEDED":
                try:
                    validate_cash_deposit_charge(
                        charge,
                        CashDepositChargeSnapshot(
                            total_amount_satang=int(attempt.get("totalAmountSatang", 0)),
                            currency=str(attempt.get("currency", "")),
                            provider_reference_id=str(attempt.get("providerReferenceId", "")),
                            attempt_created_at=attempt.get("createdAt"),
                            attempt_expires_at=attempt.get("expiresAt"),
                        ),
                        expected_merchant_id=expected_merchant_id,
                    )
                    final_status = CashDepositStatus.COMPLETED.value
                    attempt_status = "SUCCEEDED"
                except (FinancialConflict, TypeError) as error:
                    final_status = CashDepositStatus.REVIEW.value
                    attempt_status = "PAYMENT_REVIEW"
                    review_reason = str(error)
            elif charge.status in {"EXPIRED", "CANCELED", "CANCELLED"}:
                final_status = CashDepositStatus.EXPIRED.value
                attempt_status = "EXPIRED"
            for payment_ref, guard_ref, payment_snapshot, guard_snapshot in zip(
                payment_refs, guard_refs, payment_snapshots, guard_snapshots, strict=True
            ):
                if not payment_snapshot.exists or not guard_snapshot.exists:
                    raise FinancialConflict("Cash allocation state is incomplete")
                payment = payment_snapshot.to_dict() or {}
                guard = guard_snapshot.to_dict() or {}
                if (
                    payment.get("cashDepositId") != deposit_ref.id
                    or payment.get("cashSettlementStatus")
                    not in {
                        CashSettlementStatus.DEPOSIT_PENDING.value,
                        CashSettlementStatus.SETTLED.value,
                        CashSettlementStatus.REVIEW.value,
                    }
                    or guard.get("depositId") != deposit_ref.id
                ):
                    raise FinancialConflict("Cash allocation changed before settlement")
                if final_status == CashDepositStatus.COMPLETED.value:
                    transaction.update(
                        payment_ref,
                        {
                            "cashSettlementStatus": CashSettlementStatus.SETTLED.value,
                            "cashSettledAt": charge.transaction_time,
                            "cashDepositProviderResourceId": charge.charge_id,
                            "version": int(payment.get("version", 1)) + 1,
                            "updatedAt": now,
                        },
                    )
                    transaction.update(
                        guard_ref, {"active": False, "terminalStatus": "SETTLED", "updatedAt": now}
                    )
                elif final_status == CashDepositStatus.REVIEW.value:
                    transaction.update(
                        payment_ref,
                        {
                            "cashSettlementStatus": CashSettlementStatus.REVIEW.value,
                            "version": int(payment.get("version", 1)) + 1,
                            "updatedAt": now,
                        },
                    )
            transaction.update(
                attempt_ref,
                {
                    "status": attempt_status,
                    "providerStatus": charge.status,
                    "providerTransactionAt": charge.transaction_time,
                    "lastReconciledAt": now,
                    "reviewReason": review_reason,
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )
            transaction.update(
                deposit_ref,
                {
                    "status": final_status,
                    "activeAttemptId": None
                    if final_status != CashDepositStatus.QR_ACTIVE.value
                    else attempt_ref.id,
                    "settledAt": charge.transaction_time
                    if final_status == CashDepositStatus.COMPLETED.value
                    else None,
                    "reviewReason": review_reason,
                    "version": int(deposit.get("version", 1)) + 1,
                    "updatedAt": now,
                },
            )
            event_data = {
                "provider": "BEAM",
                "purpose": "CASH_DEPOSIT",
                "eventType": event_type,
                "providerResourceId": charge.charge_id,
                "cashDepositId": deposit_ref.id,
                "status": "PROCESSED",
                "receivedAt": (event_snapshot.to_dict() or {}).get("receivedAt", now)
                if event_snapshot.exists
                else now,
                "processedAt": now,
                "updatedAt": now,
            }
            if event_snapshot.exists:
                transaction.update(event_ref, event_data)
            else:
                transaction.create(event_ref, event_data)
            transaction.create(
                self._client.collection("audit_events").document(),
                {
                    "eventType": "CASH_DEPOSIT_SETTLEMENT_UPDATED",
                    "actorType": "SERVICE",
                    "depositId": deposit_ref.id,
                    "attemptId": attempt_ref.id,
                    "providerResourceId": charge.charge_id,
                    "result": final_status,
                    "createdAt": now,
                    "retentionUntil": now + timedelta(days=365 * 7),
                },
            )
            return True

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit settlement is unavailable") from error

    async def attempt_reconciliation_target(
        self, attempt_id: str, *, branch_ids: tuple[str, ...]
    ) -> tuple[str | None, str]:
        attempt = await self._client.collection("cash_deposit_attempts").document(attempt_id).get()
        data = attempt.to_dict() if attempt.exists else {}
        if not attempt.exists or data.get("branchId") not in branch_ids:
            raise NotFoundDomainError("Cash deposit attempt not found")
        reference_id = data.get("providerReferenceId")
        charge_id = data.get("providerChargeId")
        if not isinstance(reference_id, str) or not reference_id:
            raise FinancialConflict("Cash deposit attempt reference is missing")
        if charge_id is not None and not isinstance(charge_id, str):
            raise FinancialConflict("Cash deposit attempt charge reference is invalid")
        return charge_id, reference_id

    async def link_discovered_charge(
        self, attempt_id: str, charge: BeamCharge, *, now: datetime
    ) -> None:
        attempt_ref = self._client.collection("cash_deposit_attempts").document(attempt_id)
        link_ref = self._client.collection("beam_charge_links").document(charge.charge_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            attempt_snapshot = await _one(transaction, attempt_ref)
            link_snapshot = await _one(transaction, link_ref)
            if not attempt_snapshot.exists:
                raise NotFoundDomainError("Cash deposit attempt not found")
            attempt = attempt_snapshot.to_dict() or {}
            if (
                attempt.get("providerReferenceId") != charge.reference_id
                or charge.merchant_id != self._settings.beam_merchant_id
                or charge.currency != attempt.get("currency")
                or charge.amount != attempt.get("totalAmountSatang")
            ):
                raise FinancialConflict("Discovered Beam charge does not match cash deposit")
            if link_snapshot.exists:
                link = link_snapshot.to_dict() or {}
                if link.get("attemptId") != attempt_id or link.get("purpose") != "CASH_DEPOSIT":
                    raise FinancialConflict("Beam charge is already linked to another purpose")
            else:
                transaction.create(
                    link_ref,
                    {
                        "purpose": "CASH_DEPOSIT",
                        "cashDepositId": attempt.get("depositId"),
                        "attemptId": attempt_id,
                        "providerReferenceId": charge.reference_id,
                        "createdAt": now,
                    },
                )
            transaction.update(
                attempt_ref,
                {
                    "providerChargeId": charge.charge_id,
                    "lastReconciledAt": now,
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit charge link is unavailable") from error

    async def get_by_attempt(self, attempt_id: str, *, branch_ids: tuple[str, ...]) -> dict:
        attempt = await self._client.collection("cash_deposit_attempts").document(attempt_id).get()
        data = attempt.to_dict() if attempt.exists else {}
        if not attempt.exists or data.get("branchId") not in branch_ids:
            raise NotFoundDomainError("Cash deposit attempt not found")
        return await self.get(str(data.get("depositId", "")), branch_ids=branch_ids)

    async def cancel(
        self,
        deposit_id: str,
        *,
        principal: AdminPrincipal,
        expected_version: int,
        reason: str,
        now: datetime,
    ) -> dict:
        if not reason.strip() or len(reason.strip()) > 500:
            raise CashDepositNotEligible("Cancellation reason is required")
        deposit_ref = self._deposit_ref(deposit_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            snapshot = await _one(transaction, deposit_ref)
            if not snapshot.exists:
                raise NotFoundDomainError("Cash deposit not found")
            data = snapshot.to_dict() or {}
            if (
                data.get("branchId") not in principal.branch_ids
                or int(data.get("version", 1)) != expected_version
            ):
                raise ConflictDomainError("Cash deposit version changed")
            if data.get("status") not in {
                CashDepositStatus.DRAFT.value,
                CashDepositStatus.EVIDENCE_UPLOADING.value,
                CashDepositStatus.READY_FOR_QR.value,
            } or data.get("latestAttemptId"):
                raise CashDepositNotEligible("Cash deposit can no longer be cancelled")
            allocations = data.get("allocations") or []
            payment_refs = [
                self._client.collection("payments").document(str(row.get("paymentId", "")))
                for row in allocations
            ]
            guard_refs = [
                self._client.collection("cash_deposit_allocation_guards").document(ref.id)
                for ref in payment_refs
            ]
            payment_snapshots = [await _one(transaction, ref) for ref in payment_refs]
            guard_snapshots = [await _one(transaction, ref) for ref in guard_refs]
            for payment_ref, guard_ref, payment_snapshot, guard_snapshot in zip(
                payment_refs, guard_refs, payment_snapshots, guard_snapshots, strict=True
            ):
                payment = payment_snapshot.to_dict() or {}
                guard = guard_snapshot.to_dict() or {}
                if (
                    not payment_snapshot.exists
                    or not guard_snapshot.exists
                    or payment.get("cashDepositId") != deposit_id
                    or guard.get("depositId") != deposit_id
                ):
                    raise FinancialConflict("Cash allocation changed before cancellation")
                transaction.update(
                    payment_ref,
                    {
                        "cashSettlementStatus": CashSettlementStatus.UNSETTLED.value,
                        "cashDepositId": None,
                        "version": int(payment.get("version", 1)) + 1,
                        "updatedAt": now,
                    },
                )
                transaction.update(
                    guard_ref, {"active": False, "terminalStatus": "CANCELLED", "updatedAt": now}
                )
            transaction.update(
                deposit_ref,
                {
                    "status": CashDepositStatus.CANCELLED.value,
                    "cancelReason": reason.strip(),
                    "cancelledBy": principal.uid,
                    "cancelledAt": now,
                    "version": expected_version + 1,
                    "updatedAt": now,
                },
            )
            transaction.create(
                self._client.collection("audit_events").document(),
                {
                    "eventType": "CASH_DEPOSIT_CANCELLED",
                    "actorType": "ADMIN_USER",
                    "actorId": principal.uid,
                    "depositId": deposit_id,
                    "reason": reason.strip(),
                    "createdAt": now,
                    "retentionUntil": now + timedelta(days=365 * 7),
                },
            )

        try:
            await run(self._client.transaction())
            return await self.get(deposit_id, branch_ids=principal.branch_ids)
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash deposit cancellation is unavailable") from error

    async def evidence_pointer(
        self, deposit_id: str, *, branch_ids: tuple[str, ...]
    ) -> tuple[str, int]:
        deposit = await self.get(deposit_id, branch_ids=branch_ids)
        evidence = deposit.get("evidence") or {}
        if evidence.get("status") != "READY" or not isinstance(evidence.get("generation"), int):
            raise CashDepositEvidenceInvalid("Verified cash evidence is unavailable")
        return str(evidence.get("objectName", "")), int(evidence["generation"])
