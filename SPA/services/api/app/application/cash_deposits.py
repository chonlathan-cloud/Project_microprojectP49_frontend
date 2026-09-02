from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol

from app.core.errors import (
    CashDepositDisabled,
    CashDepositEvidenceInvalid,
    CashDepositReconciliationRequired,
    DependencyUnavailable,
    FinancialConflict,
)
from app.core.settings import Settings
from app.core.types import BeamPaymentMethod
from app.domains.identity.models import AdminPrincipal
from app.domains.payments.policy import (
    AdminFinancialAction,
    require_admin_financial_action,
)
from app.integrations.beam import (
    BeamAmbiguousCreateError,
    BeamCharge,
    BeamClient,
    BeamConfigurationError,
    BeamRejectedError,
    BeamRetryableError,
    normalize_charge_action,
)


@dataclass(frozen=True, slots=True)
class CashAllocationRequest:
    payment_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class EvidenceAuthorization:
    evidence_id: str
    upload_url: str
    object_name: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedEvidence:
    generation: int
    size_bytes: int
    content_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedCashDepositAttempt:
    deposit_id: str
    attempt_id: str
    total_amount_satang: int
    currency: str
    provider_reference_id: str
    provider_idempotency_key: str
    requested_expires_at: datetime
    is_replay: bool = False


class CashEvidenceStore(Protocol):
    async def authorize_upload(
        self,
        *,
        evidence_id: str,
        object_name: str,
        content_type: str,
    ) -> EvidenceAuthorization: ...

    async def verify_upload(
        self,
        *,
        object_name: str,
        generation: int,
        expected_size_bytes: int,
        expected_content_type: str,
        expected_sha256: str,
    ) -> VerifiedEvidence: ...

    async def authorize_read(
        self, *, object_name: str, generation: int
    ) -> tuple[str, datetime]: ...


class CashDepositRepository(Protocol):
    async def list_unsettled(
        self, *, branch_ids: tuple[str, ...], branch_id: str
    ) -> list[dict]: ...
    async def create_draft(
        self,
        *,
        principal: AdminPrincipal,
        branch_id: str,
        allocations: tuple[CashAllocationRequest, ...],
        expected_total_satang: int,
        idempotency_key: str,
        now: datetime,
    ) -> dict: ...
    async def get(self, deposit_id: str, *, branch_ids: tuple[str, ...]) -> dict: ...
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
    ) -> None: ...
    async def confirm_evidence(
        self, *, deposit_id: str, principal: AdminPrincipal, generation: int, now: datetime
    ) -> dict: ...
    async def begin_attempt(
        self,
        *,
        deposit_id: str,
        principal: AdminPrincipal,
        expected_version: int,
        idempotency_key: str,
        now: datetime,
        expires_at: datetime,
    ) -> PreparedCashDepositAttempt: ...
    async def activate_attempt(
        self,
        prepared: PreparedCashDepositAttempt,
        *,
        provider_charge_id: str,
        provider_expires_at: datetime | None,
        now: datetime,
    ) -> None: ...
    async def mark_attempt_unknown(self, attempt_id: str, *, now: datetime) -> None: ...
    async def mark_attempt_failed(self, attempt_id: str, *, now: datetime) -> None: ...
    async def cash_deposit_for_charge(self, charge_id: str) -> bool: ...
    async def settle_charge(
        self,
        *,
        event_id: str,
        event_type: str,
        charge: BeamCharge,
        expected_merchant_id: str,
        now: datetime,
    ) -> bool: ...
    async def attempt_reconciliation_target(
        self, attempt_id: str, *, branch_ids: tuple[str, ...]
    ) -> tuple[str | None, str]: ...
    async def link_discovered_charge(
        self, attempt_id: str, charge: BeamCharge, *, now: datetime
    ) -> None: ...
    async def get_by_attempt(self, attempt_id: str, *, branch_ids: tuple[str, ...]) -> dict: ...
    async def cancel(
        self,
        deposit_id: str,
        *,
        principal: AdminPrincipal,
        expected_version: int,
        reason: str,
        now: datetime,
    ) -> dict: ...
    async def evidence_pointer(
        self, deposit_id: str, *, branch_ids: tuple[str, ...]
    ) -> tuple[str, int]: ...


class CashDepositService:
    def __init__(
        self, repository: CashDepositRepository, evidence: CashEvidenceStore, settings: Settings
    ) -> None:
        self._repository = repository
        self._evidence = evidence
        self._settings = settings

    def _require_enabled(self) -> None:
        errors = self._settings.cash_deposit_readiness_errors()
        if errors:
            raise CashDepositDisabled(f"Cash deposit is unavailable: {','.join(errors)}")

    @staticmethod
    def _authorize(principal: AdminPrincipal) -> None:
        require_admin_financial_action(
            role=principal.role, action=AdminFinancialAction.CASH_DEPOSIT
        )

    async def list_unsettled(self, principal: AdminPrincipal, branch_id: str) -> list[dict]:
        self._authorize(principal)
        if branch_id not in principal.branch_ids:
            raise FinancialConflict("Branch is outside the Admin scope")
        return await self._repository.list_unsettled(
            branch_ids=principal.branch_ids, branch_id=branch_id
        )

    async def create(
        self,
        *,
        principal: AdminPrincipal,
        branch_id: str,
        allocations: tuple[CashAllocationRequest, ...],
        expected_total_satang: int,
        idempotency_key: str,
    ) -> dict:
        self._require_enabled()
        self._authorize(principal)
        if branch_id not in principal.branch_ids:
            raise FinancialConflict("Branch is outside the Admin scope")
        return await self._repository.create_draft(
            principal=principal,
            branch_id=branch_id,
            allocations=allocations,
            expected_total_satang=expected_total_satang,
            idempotency_key=idempotency_key,
            now=datetime.now(UTC),
        )

    async def get(self, deposit_id: str, principal: AdminPrincipal) -> dict:
        self._authorize(principal)
        return await self._repository.get(deposit_id, branch_ids=principal.branch_ids)

    async def authorize_evidence(
        self,
        *,
        deposit_id: str,
        principal: AdminPrincipal,
        content_type: str,
        size_bytes: int,
        sha256_hex: str,
    ) -> EvidenceAuthorization:
        self._require_enabled()
        self._authorize(principal)
        allowed = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/heic": "heic",
            "image/heif": "heif",
        }
        if (
            content_type not in allowed
            or not 1 <= size_bytes <= self._settings.cash_evidence_max_bytes
            or len(sha256_hex) != 64
        ):
            raise CashDepositEvidenceInvalid("Cash evidence metadata is invalid")
        try:
            bytes.fromhex(sha256_hex)
        except ValueError as error:
            raise CashDepositEvidenceInvalid("Cash evidence checksum is invalid") from error
        now = datetime.now(UTC)
        current = await self._repository.get(deposit_id, branch_ids=principal.branch_ids)
        evidence_id = sha256(
            f"{deposit_id}:{principal.uid}:{now.isoformat()}".encode()
        ).hexdigest()[:32]
        object_name = (
            f"cash-deposits/{current['branchId']}/{now:%Y}/{now:%m}/"
            f"{deposit_id}/{evidence_id}.{allowed[content_type]}"
        )
        await self._repository.begin_evidence(
            deposit_id=deposit_id,
            principal=principal,
            evidence_id=evidence_id,
            object_name=object_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256_hex=sha256_hex.lower(),
            now=now,
        )
        return await self._evidence.authorize_upload(
            evidence_id=evidence_id,
            object_name=object_name,
            content_type=content_type,
        )

    async def confirm_evidence(
        self, *, deposit_id: str, principal: AdminPrincipal, generation: int
    ) -> dict:
        self._require_enabled()
        self._authorize(principal)
        current = await self._repository.get(deposit_id, branch_ids=principal.branch_ids)
        evidence = current.get("evidence") or {}
        verified = await self._evidence.verify_upload(
            object_name=str(evidence.get("objectName", "")),
            generation=generation,
            expected_size_bytes=int(evidence.get("sizeBytes", 0)),
            expected_content_type=str(evidence.get("contentType", "")),
            expected_sha256=str(evidence.get("sha256", "")),
        )
        return await self._repository.confirm_evidence(
            deposit_id=deposit_id,
            principal=principal,
            generation=verified.generation,
            now=datetime.now(UTC),
        )

    async def authorize_evidence_read(
        self, deposit_id: str, principal: AdminPrincipal
    ) -> tuple[str, datetime]:
        self._authorize(principal)
        object_name, generation = await self._repository.evidence_pointer(
            deposit_id, branch_ids=principal.branch_ids
        )
        return await self._evidence.authorize_read(object_name=object_name, generation=generation)

    async def create_attempt(
        self,
        *,
        deposit_id: str,
        principal: AdminPrincipal,
        expected_version: int,
        idempotency_key: str,
    ) -> dict:
        self._require_enabled()
        self._authorize(principal)
        now = datetime.now(UTC)
        prepared = await self._repository.begin_attempt(
            deposit_id=deposit_id,
            principal=principal,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            now=now,
            expires_at=now + timedelta(minutes=self._settings.cash_deposit_qr_expiry_minutes),
        )
        if prepared.is_replay:
            # A repeated client request must never create a second Beam charge. The
            # persisted attempt is the authoritative response and can be reconciled.
            return await self._repository.get(deposit_id, branch_ids=principal.branch_ids)
        try:
            async with BeamClient(self._settings) as client:
                raw = await client.create_qr_promptpay_charge(
                    amount_satang=prepared.total_amount_satang,
                    reference_id=prepared.provider_reference_id,
                    expires_at=prepared.requested_expires_at,
                    idempotency_key=prepared.provider_idempotency_key,
                    return_url=self._settings.cash_deposit_return_url,
                )
            action = normalize_charge_action(
                raw,
                requested_method=BeamPaymentMethod.QR_PROMPT_PAY,
                requested_expires_at=prepared.requested_expires_at,
            )
            if action.action_required != "ENCODED_IMAGE" or not action.image_base64:
                raise BeamConfigurationError("Cash deposit requires an encoded PromptPay QR")
            await self._repository.activate_attempt(
                prepared,
                provider_charge_id=action.charge_id,
                provider_expires_at=action.expires_at,
                now=datetime.now(UTC),
            )
            result = await self._repository.get(deposit_id, branch_ids=principal.branch_ids)
            attempt = result.get("attempt")
            if isinstance(attempt, dict):
                # Beam QR material is response-only and is never persisted.
                attempt["imageBase64"] = action.image_base64
            return result
        except BeamAmbiguousCreateError:
            await self._repository.mark_attempt_unknown(prepared.attempt_id, now=datetime.now(UTC))
            raise CashDepositReconciliationRequired(
                "Beam create outcome is unknown; reconcile before retrying"
            ) from None
        except (BeamRejectedError, BeamConfigurationError) as error:
            await self._repository.mark_attempt_failed(prepared.attempt_id, now=datetime.now(UTC))
            raise DependencyUnavailable("Beam rejected the cash-deposit QR request") from error
        except BeamRetryableError as error:
            await self._repository.mark_attempt_unknown(prepared.attempt_id, now=datetime.now(UTC))
            raise CashDepositReconciliationRequired(
                "Beam outcome requires reconciliation"
            ) from error

    async def process_webhook(self, *, event_id: str, event_type: str, charge: BeamCharge) -> bool:
        if not await self._repository.cash_deposit_for_charge(charge.charge_id):
            return False
        merchant_id = self._settings.beam_merchant_id
        if not merchant_id:
            raise CashDepositDisabled("Beam merchant is not configured")
        return await self._repository.settle_charge(
            event_id=event_id,
            event_type=event_type,
            charge=charge,
            expected_merchant_id=merchant_id,
            now=datetime.now(UTC),
        )

    async def process_webhook_charge(
        self, *, event_type: str, charge_id: str, raw_body: bytes
    ) -> bool:
        if not await self._repository.cash_deposit_for_charge(charge_id):
            return False
        try:
            async with BeamClient(self._settings) as client:
                charge = await client.get_charge(charge_id)
        except (BeamRetryableError, BeamRejectedError, BeamConfigurationError) as error:
            raise DependencyUnavailable(
                "Beam cash-deposit reconciliation is unavailable"
            ) from error
        event_id = sha256(event_type.encode() + b":" + raw_body).hexdigest()
        return await self.process_webhook(event_id=event_id, event_type=event_type, charge=charge)

    async def reconcile(self, attempt_id: str, principal: AdminPrincipal) -> dict:
        self._require_enabled()
        self._authorize(principal)
        charge_id, reference_id = await self._repository.attempt_reconciliation_target(
            attempt_id, branch_ids=principal.branch_ids
        )
        try:
            async with BeamClient(self._settings) as client:
                if charge_id:
                    charge = await client.get_charge(charge_id)
                else:
                    charges = await client.list_charges_by_reference(reference_id)
                    if charges.total_count != 1 or len(charges.charges) != 1:
                        raise CashDepositReconciliationRequired(
                            "Beam reference is missing or ambiguous; Finance review is required"
                        )
                    charge = charges.charges[0]
        except (BeamRetryableError, BeamRejectedError, BeamConfigurationError) as error:
            raise DependencyUnavailable("Beam reconciliation is unavailable") from error
        if not charge_id:
            await self._repository.link_discovered_charge(attempt_id, charge, now=datetime.now(UTC))
        event_id = sha256(
            f"cash-deposit-reconcile:{charge.charge_id}:{charge.status}".encode()
        ).hexdigest()
        await self.process_webhook(event_id=event_id, event_type="charge.reconcile", charge=charge)
        return await self._repository.get_by_attempt(attempt_id, branch_ids=principal.branch_ids)

    async def cancel(
        self, *, deposit_id: str, principal: AdminPrincipal, expected_version: int, reason: str
    ) -> dict:
        self._require_enabled()
        self._authorize(principal)
        return await self._repository.cancel(
            deposit_id,
            principal=principal,
            expected_version=expected_version,
            reason=reason,
            now=datetime.now(UTC),
        )
