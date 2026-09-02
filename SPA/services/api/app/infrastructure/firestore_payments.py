from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import GoogleAPICallError
from google.cloud.firestore_v1 import AsyncClient, AsyncTransaction
from google.cloud.firestore_v1.async_transaction import async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter

from app.application.payments import (
    BookingDiscountResult,
    CustomerPaymentResult,
    PaymentOptions,
    PaymentReconciliationTarget,
    PaymentStatusResult,
    PreparedAttempt,
    customer_tip_presets,
)
from app.core.errors import (
    AuthenticationInvalid,
    FinancialConflict,
    PaymentNotEligible,
    PersistenceUnavailable,
)
from app.core.settings import Settings
from app.core.types import (
    BeamPaymentMethod,
    BookingStatus,
    CashSettlementStatus,
    PaymentAttemptStatus,
    PaymentSource,
    PaymentStatus,
)
from app.domains.accounting.factory import build_accounting_export
from app.domains.accounting.models import AccountingExport
from app.domains.bookings.pricing import validate_fixed_discount
from app.domains.identity.models import AdminPrincipal, LinePrincipal
from app.domains.payments.eligibility import (
    PaymentEligibility,
    attempt_expires_at,
    evaluate_payment_eligibility,
)
from app.domains.payments.models import MoneyBreakdown, Payment, ServiceLineSnapshot
from app.infrastructure.firestore import firestore_client
from app.integrations.beam import BeamCharge, validate_authoritative_charge

_RECONCILABLE_ATTEMPT_STATUSES = {
    PaymentAttemptStatus.CREATING,
    PaymentAttemptStatus.CREATE_UNKNOWN,
    PaymentAttemptStatus.ACTIVE,
}


def _reconciliation_target(
    attempt_snapshot: Any | None,
    attempt: dict[str, Any],
) -> PaymentReconciliationTarget | None:
    if attempt_snapshot is None or not attempt_snapshot.exists:
        return None
    if attempt.get("status") not in _RECONCILABLE_ATTEMPT_STATUSES:
        return None
    provider_reference_id = attempt.get("providerReferenceId")
    provider_charge_id = attempt.get("providerChargeId")
    payment_id = attempt.get("paymentId")
    expires_at = attempt.get("expiresAt")
    if (
        not isinstance(provider_reference_id, str)
        or not provider_reference_id
        or (provider_charge_id is not None and not isinstance(provider_charge_id, str))
        or not isinstance(payment_id, str)
        or not payment_id
        or not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
    ):
        raise PersistenceUnavailable("Payment reconciliation state is invalid")
    return PaymentReconciliationTarget(
        attempt_id=attempt_snapshot.id,
        payment_id=payment_id,
        provider_reference_id=provider_reference_id,
        provider_charge_id=provider_charge_id,
        expires_at=expires_at,
    )


def _charge_link_attempt_updates(
    attempt: dict[str, Any], charge: BeamCharge, now: datetime
) -> dict[str, Any]:
    """Link an authoritative charge without inventing a missing browser action.

    A charge discovered after an ambiguous create may be PENDING, but the GET/list
    contract does not return the original redirect URL or encoded image. Keeping the
    attempt in CREATE_UNKNOWN prevents the UI from presenting an ACTIVE attempt that
    the customer cannot complete.
    """
    return {
        "providerChargeId": charge.charge_id,
        "lastReconciledAt": now,
        "updatedAt": now,
        "version": int(attempt.get("version", 1)) + 1,
    }


async def _snapshots(transaction: AsyncTransaction, reference_or_query: Any) -> list[Any]:
    stream = await transaction.get(reference_or_query)
    return [snapshot async for snapshot in stream]


async def _one(transaction: AsyncTransaction, reference: Any) -> Any:
    return await reference.get(transaction=transaction)


def _payment_id(booking_doc_id: str) -> str:
    return "pay_" + sha256(f"booking:{booking_doc_id}".encode()).hexdigest()[:26]


def _status_token_id(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _idempotency_id(scope: str, key: str) -> str:
    return sha256(f"{scope}:{key}".encode()).hexdigest()


def _service_lines(snapshots: list[Any]) -> tuple[ServiceLineSnapshot, ...]:
    lines: list[ServiceLineSnapshot] = []
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        service = data.get("serviceSnapshot") or {}
        name = service.get("nameTh") or service.get("nameEn")
        sku = service.get("variantId") or service.get("serviceId")
        quantity = data.get("quantity")
        line_total = data.get("lineTotalSatang")
        if not isinstance(name, str) or not isinstance(sku, str):
            raise PersistenceUnavailable("Booking line-item identity is invalid")
        if not isinstance(quantity, int) or not isinstance(line_total, int):
            raise PersistenceUnavailable("Booking line-item amount is invalid")
        if line_total == 0:
            continue
        if quantity <= 0 or line_total % quantity:
            raise PersistenceUnavailable("Booking line-item amount is not divisible by quantity")
        lines.append(ServiceLineSnapshot(sku, name, quantity, line_total // quantity))
    lines.sort(key=lambda item: (item.sku, item.name))
    if not lines:
        raise PersistenceUnavailable("Booking has no payable line items")
    return tuple(lines)


def _payment_from_data(payment_id: str, data: dict[str, Any]) -> Payment:
    raw_lines = data.get("serviceLines")
    if not isinstance(raw_lines, list):
        raise PersistenceUnavailable("Payment service snapshot is invalid")
    try:
        service_lines = tuple(
            ServiceLineSnapshot(
                sku=str(line["sku"]),
                name=str(line["name"]),
                quantity=int(line["quantity"]),
                unit_price_satang=int(line["unitPriceSatang"]),
            )
            for line in raw_lines
        )
        line_subtotal = sum(line.line_total_satang for line in service_lines)
        source_value = data.get("paymentMethod")
        return Payment(
            payment_id=payment_id,
            booking_doc_id=str(data["bookingDocId"]),
            booking_public_id=str(data["bookingPublicId"]),
            branch_id=str(data["branchId"]),
            amounts=MoneyBreakdown(
                int(data["serviceAmountSatang"]),
                int(data.get("tipAmountSatang", 0)),
                int(data["grossAmountSatang"]),
                str(data.get("currency", "THB")),
            ),
            service_lines=service_lines,
            subtotal_amount_satang=int(data.get("subtotalAmountSatang", line_subtotal)),
            discount_amount_satang=int(data.get("discountAmountSatang", 0)),
            discount_reason=data.get("discountReason"),
            status=PaymentStatus(data["status"]),
            source=PaymentSource(source_value) if source_value else None,
            paid_at=data.get("paidAt"),
            provider_resource_id=data.get("providerResourceId"),
            cash_received_by=data.get("cashReceivedBy"),
            cash_settlement_status=CashSettlementStatus(
                data.get("cashSettlementStatus", CashSettlementStatus.NOT_APPLICABLE)
            ),
            version=int(data.get("version", 1)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PersistenceUnavailable("Payment data is invalid") from error


def _payment_data(payment: Payment, now: datetime) -> dict[str, Any]:
    return {
        "bookingDocId": payment.booking_doc_id,
        "bookingPublicId": payment.booking_public_id,
        "branchId": payment.branch_id,
        "purpose": "SERVICE_AND_TIP",
        "status": payment.status,
        "currency": payment.amounts.currency,
        "serviceAmountSatang": payment.amounts.service_amount_satang,
        "subtotalAmountSatang": payment.subtotal_amount_satang,
        "discountAmountSatang": payment.discount_amount_satang,
        "discountReason": payment.discount_reason,
        "tipAmountSatang": payment.amounts.tip_amount_satang,
        "grossAmountSatang": payment.amounts.gross_amount_satang,
        "paidAmountSatang": (
            payment.amounts.gross_amount_satang if payment.status is PaymentStatus.PAID else 0
        ),
        "paymentMethod": payment.source,
        "providerResourceId": payment.provider_resource_id,
        "cashReceivedBy": payment.cash_received_by,
        "cashSettlementStatus": payment.cash_settlement_status,
        "paidAt": payment.paid_at,
        "serviceLines": [
            {
                "sku": line.sku,
                "name": line.name,
                "quantity": line.quantity,
                "unitPriceSatang": line.unit_price_satang,
            }
            for line in payment.service_lines
        ],
        "payableSnapshotVersion": 2,
        "version": payment.version,
        "updatedAt": now,
    }


def _new_payment(
    booking_doc_id: str,
    booking: dict[str, Any],
    lines: tuple[ServiceLineSnapshot, ...],
) -> Payment:
    line_subtotal = sum(line.line_total_satang for line in lines)
    subtotal = booking.get("subtotalAmountSatang", line_subtotal)
    discount = booking.get("discountAmountSatang", 0)
    expected = booking.get("estimatedAmountSatang")
    if (
        isinstance(subtotal, bool)
        or not isinstance(subtotal, int)
        or subtotal != line_subtotal
        or isinstance(discount, bool)
        or not isinstance(discount, int)
        or discount < 0
        or discount >= subtotal
        or isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != subtotal - discount
    ):
        raise FinancialConflict("Booking payable snapshot does not match line items")
    discount_reason = booking.get("discountReason")
    if discount and (not isinstance(discount_reason, str) or not discount_reason.strip()):
        raise FinancialConflict("Booking discount reason is missing")
    return Payment(
        payment_id=_payment_id(booking_doc_id),
        booking_doc_id=booking_doc_id,
        booking_public_id=str(booking["publicBookingId"]),
        branch_id=str(booking["branchId"]),
        amounts=MoneyBreakdown(expected, 0, expected),
        service_lines=lines,
        subtotal_amount_satang=subtotal,
        discount_amount_satang=discount,
        discount_reason=discount_reason if discount else None,
    )


def _with_tip(payment: Payment, tip_amount_satang: int) -> Payment:
    return Payment(
        payment_id=payment.payment_id,
        booking_doc_id=payment.booking_doc_id,
        booking_public_id=payment.booking_public_id,
        branch_id=payment.branch_id,
        amounts=MoneyBreakdown(
            payment.amounts.service_amount_satang,
            tip_amount_satang,
            payment.amounts.service_amount_satang + tip_amount_satang,
        ),
        service_lines=payment.service_lines,
        subtotal_amount_satang=payment.subtotal_amount_satang,
        discount_amount_satang=payment.discount_amount_satang,
        discount_reason=payment.discount_reason,
        status=payment.status,
        source=payment.source,
        paid_at=payment.paid_at,
        provider_resource_id=payment.provider_resource_id,
        cash_received_by=payment.cash_received_by,
        cash_settlement_status=payment.cash_settlement_status,
        version=payment.version + 1,
    )


def _with_discount(
    payment: Payment,
    *,
    discount_amount_satang: int,
    reason: str,
) -> Payment:
    normalized_reason = validate_fixed_discount(
        subtotal_amount_satang=int(payment.subtotal_amount_satang or 0),
        discount_amount_satang=discount_amount_satang,
        reason=reason,
    )
    service_amount_satang = int(payment.subtotal_amount_satang or 0) - discount_amount_satang
    return Payment(
        payment_id=payment.payment_id,
        booking_doc_id=payment.booking_doc_id,
        booking_public_id=payment.booking_public_id,
        branch_id=payment.branch_id,
        amounts=MoneyBreakdown(
            service_amount_satang,
            payment.amounts.tip_amount_satang,
            service_amount_satang + payment.amounts.tip_amount_satang,
        ),
        service_lines=payment.service_lines,
        subtotal_amount_satang=payment.subtotal_amount_satang,
        discount_amount_satang=discount_amount_satang,
        discount_reason=normalized_reason if discount_amount_satang else None,
        status=payment.status,
        source=payment.source,
        paid_at=payment.paid_at,
        provider_resource_id=payment.provider_resource_id,
        cash_received_by=payment.cash_received_by,
        cash_settlement_status=payment.cash_settlement_status,
        version=payment.version + 1,
    )


def _status_result(payment: Payment) -> PaymentStatusResult:
    return PaymentStatusResult(
        payment_id=payment.payment_id,
        booking_id=payment.booking_public_id,
        status=payment.status,
        source=payment.source,
        service_amount_satang=payment.amounts.service_amount_satang,
        tip_amount_satang=payment.amounts.tip_amount_satang,
        gross_amount_satang=payment.amounts.gross_amount_satang,
        paid_at=payment.paid_at,
    )


def _export_data(export: AccountingExport, now: datetime) -> dict[str, Any]:
    return {
        "exportKey": export.export_key,
        "provider": export.provider,
        "paymentId": export.payment_id,
        "bookingDocId": export.booking_doc_id,
        "bookingPublicId": export.booking_public_id,
        "branchId": export.branch_id,
        "purpose": "CUSTOMER_SALE",
        "businessUnitCode": export.business_unit_code,
        "projectName": export.project_name,
        "accountingDate": export.accounting_date.isoformat(),
        "paidAt": export.paid_at,
        "documentIntent": export.document_intent,
        "paymentSource": export.payment_source,
        "flowAccountContactStrategy": export.flow_account_contact_strategy,
        "flowAccountPaymentStrategy": export.payment_strategy,
        "vatPolicyVersion": export.vat_policy_version,
        "serviceAmountSatang": export.service_amount_satang,
        "subtotalAmountSatang": export.subtotal_amount_satang,
        "discountAmountSatang": export.discount_amount_satang,
        "discountReason": export.discount_reason,
        "tipAmountSatang": export.tip_amount_satang,
        "grossAmountSatang": export.gross_amount_satang,
        "currency": export.currency,
        "serviceLines": [
            {
                "sku": line.sku,
                "name": line.name,
                "quantity": line.quantity,
                "unitAmountSatang": line.unit_price_satang,
            }
            for line in export.service_lines
        ],
        "externalReference": export.external_reference,
        "externalDocumentId": export.external_document_id,
        "sourceSnapshotVersion": export.source_snapshot_version,
        "status": export.status,
        "attemptCount": export.attempt_count,
        "nextAttemptAt": now,
        "leaseOwner": None,
        "leaseExpiresAt": None,
        "createdAt": now,
        "updatedAt": now,
        "expiresAt": export.paid_at + timedelta(days=365 * 7),
    }


class FirestorePaymentRepository:
    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        if settings.resolved_firestore_database != settings.expected_firestore_database:
            raise PersistenceUnavailable("Firestore database does not match runtime environment")
        self._settings = settings
        self._client = client or firestore_client(
            settings.gcp_project_id, settings.resolved_firestore_database
        )

    async def _booking_context(
        self,
        transaction: AsyncTransaction,
        booking_public_id: str,
        principal: LinePrincipal | None,
    ) -> tuple[Any, dict[str, Any], tuple[ServiceLineSnapshot, ...], Any, Any]:
        booking_query = (
            self._client.collection("bookings")
            .where(filter=FieldFilter("publicBookingId", "==", booking_public_id))
            .limit(2)
        )
        bookings = await _snapshots(transaction, booking_query)
        if len(bookings) != 1:
            raise PaymentNotEligible("Booking is unavailable for payment")
        booking_snapshot = bookings[0]
        booking = booking_snapshot.to_dict() or {}
        if principal is not None:
            link_query = (
                self._client.collection("line_booking_links")
                .where(filter=FieldFilter("lineUserId", "==", principal.user_id))
                .limit(50)
            )
            links = await _snapshots(transaction, link_query)
            if not any(
                (link.to_dict() or {}).get("bookingDocId") == booking_snapshot.id
                and (link.to_dict() or {}).get("channelId") == principal.channel_id
                and (link.to_dict() or {}).get("active") is True
                for link in links
            ):
                raise AuthenticationInvalid("Booking is not linked to this LINE identity")
        line_query = self._client.collection("booking_line_items").where(
            filter=FieldFilter("bookingDocId", "==", booking_snapshot.id)
        )
        lines = _service_lines(await _snapshots(transaction, line_query))
        payment_ref = self._client.collection("payments").document(_payment_id(booking_snapshot.id))
        payment_snapshot = await _one(transaction, payment_ref)
        return booking_snapshot, booking, lines, payment_ref, payment_snapshot

    async def get_options(
        self, booking_public_id: str, principal: LinePrincipal, now: datetime
    ) -> PaymentOptions:
        @async_transactional
        async def run(transaction: AsyncTransaction) -> PaymentOptions:
            (
                booking_snapshot,
                booking,
                lines,
                payment_ref,
                payment_snapshot,
            ) = await self._booking_context(transaction, booking_public_id, principal)
            guard_ref = self._client.collection("payment_attempt_guards").document(
                booking_snapshot.id
            )
            guard_snapshot = await _one(transaction, guard_ref)
            guard = guard_snapshot.to_dict() or {}
            guarded_attempt_snapshot = None
            if isinstance(guard.get("attemptId"), str):
                guarded_attempt_snapshot = await _one(
                    transaction,
                    self._client.collection("payment_attempts").document(guard["attemptId"]),
                )
            payment = (
                _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
                if payment_snapshot.exists
                else _new_payment(booking_snapshot.id, booking, lines)
            )
            expires_at = guard.get("expiresAt")
            has_active = (
                guard.get("active") is True
                and isinstance(expires_at, datetime)
                and expires_at > now
            )
            try:
                booking_status = BookingStatus(booking.get("status"))
                local_date = date.fromisoformat(str(booking["localDate"]))
            except (KeyError, ValueError) as error:
                raise PersistenceUnavailable("Booking payment state is invalid") from error
            eligibility = evaluate_payment_eligibility(
                booking_status=booking_status,
                booking_local_date=local_date,
                payment_status=payment.status,
                amount_due_satang=payment.amounts.gross_amount_satang,
                has_unexpired_attempt=has_active,
                on_correction_hold=booking.get("paymentCorrectionHold") is True,
                now=now,
                late_override_until=booking.get("paymentLateOverrideUntil"),
            )
            guarded_attempt = (
                guarded_attempt_snapshot.to_dict() or {}
                if guarded_attempt_snapshot is not None and guarded_attempt_snapshot.exists
                else {}
            )
            reconciliation = _reconciliation_target(
                guarded_attempt_snapshot,
                guarded_attempt,
            )
            if not has_active and guarded_attempt.get("status") in {
                PaymentAttemptStatus.CREATING,
                PaymentAttemptStatus.CREATE_UNKNOWN,
                PaymentAttemptStatus.ACTIVE,
                PaymentAttemptStatus.PAYMENT_REVIEW,
            }:
                eligibility = PaymentEligibility(False, "PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED")
            if not payment_snapshot.exists and booking_status is BookingStatus.COMPLETED:
                transaction.create(
                    payment_ref,
                    {**_payment_data(payment, now), "createdAt": now},
                )
                transaction.update(
                    booking_snapshot.reference,
                    {
                        "paymentStatus": PaymentStatus.DUE,
                        "amountDueSatang": payment.amounts.gross_amount_satang,
                        "paidAmountSatang": 0,
                        "paymentUpdatedAt": now,
                    },
                )
            return PaymentOptions(
                booking_id=booking_public_id,
                payment_id=payment.payment_id,
                status=payment.status,
                source=payment.source,
                service_amount_satang=payment.amounts.service_amount_satang,
                currency=payment.amounts.currency,
                eligible=eligibility.eligible,
                reason=eligibility.reason,
                tip_presets_satang=customer_tip_presets(self._settings),
                custom_tip_max_satang=self._settings.tip_custom_max_satang,
                enabled_methods=(
                    self._settings.configured_beam_payment_methods
                    if not self._settings.beam_readiness_errors()
                    else ()
                ),
                version=payment.version,
                reconciliation=reconciliation,
            )

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment store is unavailable") from error

    async def get_admin_options(
        self, booking_public_id: str, principal: AdminPrincipal, now: datetime
    ) -> PaymentOptions:
        @async_transactional
        async def run(transaction: AsyncTransaction) -> PaymentOptions:
            booking_snapshot, booking, lines, payment_ref, payment_snapshot = (
                await self._booking_context(transaction, booking_public_id, None)
            )
            principal.require_branch(str(booking.get("branchId", "")))
            payment = (
                _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
                if payment_snapshot.exists
                else _new_payment(booking_snapshot.id, booking, lines)
            )
            guard_ref = self._client.collection("payment_attempt_guards").document(
                booking_snapshot.id
            )
            guard_snapshot = await _one(transaction, guard_ref)
            guard = guard_snapshot.to_dict() or {}
            guarded_attempt: dict[str, Any] = {}
            guarded_attempt_snapshot = None
            if isinstance(guard.get("attemptId"), str):
                guarded_attempt_snapshot = await _one(
                    transaction,
                    self._client.collection("payment_attempts").document(guard["attemptId"]),
                )
                if guarded_attempt_snapshot.exists:
                    guarded_attempt = guarded_attempt_snapshot.to_dict() or {}
            reconciliation = _reconciliation_target(
                guarded_attempt_snapshot,
                guarded_attempt,
            )
            expires_at = guard.get("expiresAt")
            has_active = (
                guard.get("active") is True
                and isinstance(expires_at, datetime)
                and expires_at > now
            )
            unresolved_attempt = guarded_attempt.get("status") in {
                PaymentAttemptStatus.CREATING,
                PaymentAttemptStatus.CREATE_UNKNOWN,
                PaymentAttemptStatus.ACTIVE,
                PaymentAttemptStatus.PAYMENT_REVIEW,
            }
            try:
                booking_status = BookingStatus(booking.get("status"))
            except ValueError as error:
                raise PersistenceUnavailable("Booking payment state is invalid") from error
            eligible = (
                booking_status is BookingStatus.COMPLETED
                and payment.status in {PaymentStatus.DUE, PaymentStatus.PAYMENT_PENDING}
                and booking.get("paymentCorrectionHold") is not True
                and not has_active
                and not unresolved_attempt
            )
            reason = None
            if booking_status is not BookingStatus.COMPLETED:
                reason = "BOOKING_NOT_COMPLETED"
            elif payment.status is PaymentStatus.PAID:
                reason = "NOTHING_DUE"
            elif booking.get("paymentCorrectionHold") is True:
                reason = "PAYMENT_REVIEW_REQUIRED"
            elif has_active:
                reason = "ACTIVE_ATTEMPT_EXISTS"
            elif unresolved_attempt:
                reason = "PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED"
            elif payment.status not in {PaymentStatus.DUE, PaymentStatus.PAYMENT_PENDING}:
                reason = "PAYMENT_REVIEW_REQUIRED"
            if not payment_snapshot.exists and booking_status is BookingStatus.COMPLETED:
                transaction.create(payment_ref, {**_payment_data(payment, now), "createdAt": now})
                transaction.update(
                    booking_snapshot.reference,
                    {
                        "paymentStatus": PaymentStatus.DUE,
                        "amountDueSatang": payment.amounts.gross_amount_satang,
                        "paidAmountSatang": 0,
                        "paymentUpdatedAt": now,
                    },
                )
            return PaymentOptions(
                booking_id=booking_public_id,
                payment_id=payment.payment_id,
                status=payment.status,
                source=payment.source,
                service_amount_satang=payment.amounts.service_amount_satang,
                currency=payment.amounts.currency,
                eligible=eligible,
                reason=reason,
                tip_presets_satang=customer_tip_presets(self._settings),
                custom_tip_max_satang=self._settings.tip_custom_max_satang,
                enabled_methods=(),
                version=payment.version,
                reconciliation=reconciliation,
            )

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment store is unavailable") from error

    async def begin_attempt(
        self,
        *,
        booking_public_id: str,
        principal: LinePrincipal,
        tip_amount_satang: int,
        payment_method: BeamPaymentMethod,
        idempotency_key: str,
        request_digest: str,
        now: datetime,
    ) -> PreparedAttempt:
        attempt_id = "pat_" + uuid4().hex
        provider_key = str(uuid4())
        status_token = token_urlsafe(32)
        requested_expiry = attempt_expires_at(now)
        idem_ref = self._client.collection("idempotency_records").document(
            _idempotency_id(
                f"payment-attempt:{principal.channel_id}:{principal.user_id}",
                idempotency_key,
            )
        )

        @async_transactional
        async def run(transaction: AsyncTransaction) -> PreparedAttempt:
            idem_snapshot = await _one(transaction, idem_ref)
            if idem_snapshot.exists:
                data = idem_snapshot.to_dict() or {}
                if data.get("requestDigest") != request_digest:
                    raise FinancialConflict("Idempotency key was used with another payment")
                response = data.get("response")
                if not isinstance(response, dict):
                    raise PersistenceUnavailable("Payment idempotency response is invalid")
                provider_retry_until = response.get("providerRetryUntil")
                if not isinstance(provider_retry_until, datetime) or provider_retry_until <= now:
                    raise PaymentNotEligible("PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED")
                try:
                    return PreparedAttempt(
                        attempt_id=response["attemptId"],
                        payment_id=response["paymentId"],
                        provider_reference_id=response["providerReferenceId"],
                        provider_idempotency_key=response["providerIdempotencyKey"],
                        total_amount_satang=int(response["totalAmountSatang"]),
                        requested_expires_at=response["requestedExpiresAt"],
                        status_token=response["statusToken"],
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise PersistenceUnavailable("Payment idempotency data is invalid") from error

            (
                booking_snapshot,
                booking,
                lines,
                payment_ref,
                payment_snapshot,
            ) = await self._booking_context(transaction, booking_public_id, principal)
            payment = (
                _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
                if payment_snapshot.exists
                else _new_payment(booking_snapshot.id, booking, lines)
            )
            guard_ref = self._client.collection("payment_attempt_guards").document(
                booking_snapshot.id
            )
            guard_snapshot = await _one(transaction, guard_ref)
            guard = guard_snapshot.to_dict() or {}
            old_attempt_snapshot = None
            if isinstance(guard.get("attemptId"), str):
                old_attempt_snapshot = await _one(
                    transaction,
                    self._client.collection("payment_attempts").document(guard["attemptId"]),
                )
            expires_at = guard.get("expiresAt")
            has_active = (
                guard.get("active") is True
                and isinstance(expires_at, datetime)
                and expires_at > now
            )
            old_attempt = (
                old_attempt_snapshot.to_dict() or {}
                if old_attempt_snapshot is not None and old_attempt_snapshot.exists
                else {}
            )
            try:
                old_status = (
                    PaymentAttemptStatus(old_attempt["status"])
                    if old_attempt.get("status")
                    else None
                )
            except ValueError as error:
                raise PersistenceUnavailable("Payment attempt state is invalid") from error
            try:
                booking_status = BookingStatus(booking.get("status"))
                local_date = date.fromisoformat(str(booking["localDate"]))
            except (KeyError, ValueError) as error:
                raise PersistenceUnavailable("Booking payment state is invalid") from error
            eligibility = evaluate_payment_eligibility(
                booking_status=booking_status,
                booking_local_date=local_date,
                payment_status=payment.status,
                amount_due_satang=payment.amounts.gross_amount_satang,
                has_unexpired_attempt=has_active,
                on_correction_hold=booking.get("paymentCorrectionHold") is True,
                now=now,
                late_override_until=booking.get("paymentLateOverrideUntil"),
            )
            if not eligibility.eligible:
                raise PaymentNotEligible(eligibility.reason or "Payment is unavailable")
            if old_status in {
                PaymentAttemptStatus.CREATING,
                PaymentAttemptStatus.CREATE_UNKNOWN,
                PaymentAttemptStatus.ACTIVE,
                PaymentAttemptStatus.PAYMENT_REVIEW,
                PaymentAttemptStatus.SUCCEEDED,
            }:
                raise PaymentNotEligible("PAYMENT_ATTEMPT_RECONCILIATION_REQUIRED")
            payment = _with_tip(payment, tip_amount_satang)
            prepared = PreparedAttempt(
                attempt_id=attempt_id,
                payment_id=payment.payment_id,
                provider_reference_id=f"SPA-PAY-{payment.payment_id}-{attempt_id}",
                provider_idempotency_key=provider_key,
                total_amount_satang=payment.amounts.gross_amount_satang,
                requested_expires_at=requested_expiry,
                status_token=status_token,
            )
            if payment_snapshot.exists:
                transaction.update(payment_ref, _payment_data(payment, now))
            else:
                transaction.create(payment_ref, {**_payment_data(payment, now), "createdAt": now})
            transaction.create(
                self._client.collection("payment_attempts").document(attempt_id),
                {
                    "paymentId": payment.payment_id,
                    "bookingDocId": booking_snapshot.id,
                    "provider": "BEAM",
                    "providerMode": "CHARGE",
                    "providerChargeId": None,
                    "providerReferenceId": prepared.provider_reference_id,
                    "providerIdempotencyKey": provider_key,
                    "paymentMethod": payment_method,
                    "actionRequired": None,
                    "status": PaymentAttemptStatus.CREATING,
                    "serviceAmountSatang": payment.amounts.service_amount_satang,
                    "tipAmountSatang": payment.amounts.tip_amount_satang,
                    "totalAmountSatang": payment.amounts.gross_amount_satang,
                    "currency": payment.amounts.currency,
                    "expiresAt": requested_expiry,
                    "providerTransactionAt": None,
                    "version": 1,
                    "createdAt": now,
                    "updatedAt": now,
                },
            )
            transaction.set(
                guard_ref,
                {
                    "bookingDocId": booking_snapshot.id,
                    "paymentId": payment.payment_id,
                    "attemptId": attempt_id,
                    "active": True,
                    "expiresAt": requested_expiry,
                    "updatedAt": now,
                },
            )
            transaction.update(
                booking_snapshot.reference,
                {
                    "tipAmountSatang": payment.amounts.tip_amount_satang,
                    "grossAmountSatang": payment.amounts.gross_amount_satang,
                    "amountDueSatang": payment.amounts.gross_amount_satang,
                    "paymentUpdatedAt": now,
                },
            )
            transaction.create(
                self._client.collection("payment_status_tokens").document(
                    _status_token_id(status_token)
                ),
                {
                    "paymentId": payment.payment_id,
                    "attemptId": attempt_id,
                    "active": True,
                    "expiresAt": now + timedelta(days=7),
                    "createdAt": now,
                },
            )
            transaction.create(
                idem_ref,
                {
                    "scope": "PAYMENT_ATTEMPT_CREATE",
                    "requestDigest": request_digest,
                    "response": {
                        "attemptId": attempt_id,
                        "paymentId": payment.payment_id,
                        "providerReferenceId": prepared.provider_reference_id,
                        "providerIdempotencyKey": provider_key,
                        "totalAmountSatang": payment.amounts.gross_amount_satang,
                        "requestedExpiresAt": requested_expiry,
                        "providerRetryUntil": now + timedelta(hours=12),
                        "statusToken": status_token,
                    },
                    "expiresAt": now + timedelta(hours=self._settings.idempotency_ttl_hours),
                    "createdAt": now,
                },
            )
            return prepared

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment attempt store is unavailable") from error

    async def activate_attempt(
        self,
        prepared: PreparedAttempt,
        *,
        provider_charge_id: str,
        action_required: str,
        provider_expires_at: datetime | None,
        now: datetime,
    ) -> None:
        attempt_ref = self._client.collection("payment_attempts").document(prepared.attempt_id)
        payment_ref = self._client.collection("payments").document(prepared.payment_id)
        charge_ref = self._client.collection("beam_charge_links").document(provider_charge_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            attempt_snapshot = await _one(transaction, attempt_ref)
            payment_snapshot = await _one(transaction, payment_ref)
            charge_snapshot = await _one(transaction, charge_ref)
            if not attempt_snapshot.exists or not payment_snapshot.exists:
                raise FinancialConflict("Payment attempt no longer exists")
            attempt = attempt_snapshot.to_dict() or {}
            guard_ref = self._client.collection("payment_attempt_guards").document(
                str(attempt.get("bookingDocId", ""))
            )
            guard_snapshot = await _one(transaction, guard_ref)
            if attempt.get("providerReferenceId") != prepared.provider_reference_id:
                raise FinancialConflict("Payment attempt reference changed")
            guard = guard_snapshot.to_dict() or {}
            if guard.get("active") is not True or guard.get("attemptId") != prepared.attempt_id:
                raise FinancialConflict("Payment attempt guard changed before activation")
            if charge_snapshot.exists:
                link = charge_snapshot.to_dict() or {}
                if link.get("attemptId") != prepared.attempt_id:
                    raise FinancialConflict("Beam charge is already linked")
            payment = _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
            if (
                attempt.get("status") == PaymentAttemptStatus.ACTIVE
                and attempt.get("providerChargeId") == provider_charge_id
                and charge_snapshot.exists
            ):
                return
            if payment.status is PaymentStatus.PAID:
                return
            transaction.update(
                attempt_ref,
                {
                    "providerChargeId": provider_charge_id,
                    "actionRequired": action_required,
                    "expiresAt": provider_expires_at or prepared.requested_expires_at,
                    "status": PaymentAttemptStatus.ACTIVE,
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )
            transaction.set(
                charge_ref,
                {
                    "attemptId": prepared.attempt_id,
                    "paymentId": prepared.payment_id,
                    "providerReferenceId": prepared.provider_reference_id,
                    "createdAt": now,
                },
            )
            transaction.update(
                payment_ref,
                {
                    "status": PaymentStatus.PAYMENT_PENDING,
                    "activeAttemptId": prepared.attempt_id,
                    "updatedAt": now,
                    "version": payment.version + 1,
                },
            )

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment activation store is unavailable") from error

    async def mark_create_unknown(self, attempt_id: str, now: datetime) -> None:
        try:
            await (
                self._client.collection("payment_attempts")
                .document(attempt_id)
                .update(
                    {
                        "status": PaymentAttemptStatus.CREATE_UNKNOWN,
                        "updatedAt": now,
                    }
                )
            )
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment reconciliation state is unavailable") from error

    async def mark_create_failed(self, attempt_id: str, now: datetime) -> None:
        attempt_ref = self._client.collection("payment_attempts").document(attempt_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            attempt_snapshot = await _one(transaction, attempt_ref)
            if not attempt_snapshot.exists:
                raise FinancialConflict("Payment attempt no longer exists")
            attempt = attempt_snapshot.to_dict() or {}
            payment_ref = self._client.collection("payments").document(
                str(attempt.get("paymentId", ""))
            )
            guard_ref = self._client.collection("payment_attempt_guards").document(
                str(attempt.get("bookingDocId", ""))
            )
            payment_snapshot = await _one(transaction, payment_ref)
            guard_snapshot = await _one(transaction, guard_ref)
            if not payment_snapshot.exists:
                raise FinancialConflict("Payment no longer exists")
            payment = _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
            transaction.update(
                attempt_ref,
                {
                    "status": PaymentAttemptStatus.FAILED,
                    "failureCode": "PROVIDER_REJECTED",
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )
            if payment.status is not PaymentStatus.PAID:
                transaction.update(
                    payment_ref,
                    {
                        "status": PaymentStatus.DUE,
                        "activeAttemptId": None,
                        "updatedAt": now,
                        "version": payment.version + 1,
                    },
                )
            guard = guard_snapshot.to_dict() or {}
            if guard_snapshot.exists and guard.get("attemptId") == attempt_id:
                transaction.update(guard_ref, {"active": False, "updatedAt": now})

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment failure state is unavailable") from error

    async def ensure_beam_charge_link(self, charge: BeamCharge, now: datetime) -> bool:
        charge_ref = self._client.collection("beam_charge_links").document(charge.charge_id)
        try:
            existing_snapshot = await charge_ref.get()
            if existing_snapshot.exists:
                existing = existing_snapshot.to_dict() or {}
                if existing.get("providerReferenceId") != charge.reference_id:
                    raise FinancialConflict("Beam charge link reference does not match")
                attempt_id = existing.get("attemptId")
                if not isinstance(attempt_id, str) or not attempt_id:
                    raise FinancialConflict("Beam charge link is incomplete")
                attempt_ref = self._client.collection("payment_attempts").document(attempt_id)
            else:
                attempts_query = (
                    self._client.collection("payment_attempts")
                    .where(
                        filter=FieldFilter(
                            "providerReferenceId",
                            "==",
                            charge.reference_id,
                        )
                    )
                    .limit(2)
                )
                attempts = [snapshot async for snapshot in attempts_query.stream()]
                if not attempts:
                    return False
                if len(attempts) != 1:
                    raise FinancialConflict("Beam reference matches multiple payment attempts")
                attempt_ref = attempts[0].reference
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment reconciliation lookup is unavailable") from error

        @async_transactional
        async def run(transaction: AsyncTransaction) -> bool:
            charge_snapshot = await _one(transaction, charge_ref)
            attempt_snapshot = await _one(transaction, attempt_ref)
            if not attempt_snapshot.exists:
                return False
            attempt = attempt_snapshot.to_dict() or {}
            if attempt.get("providerReferenceId") != charge.reference_id:
                raise FinancialConflict("Beam reference changed during reconciliation")
            if charge.merchant_id != self._settings.beam_merchant_id:
                raise FinancialConflict("Beam merchant does not match configured merchant")
            if charge.currency != attempt.get("currency"):
                raise FinancialConflict("Beam currency does not match payment attempt")
            if (
                isinstance(charge.amount, bool)
                or not isinstance(charge.amount, int)
                or charge.amount != attempt.get("totalAmountSatang")
            ):
                raise FinancialConflict("Beam amount does not match payment attempt")
            if charge_snapshot.exists:
                link = charge_snapshot.to_dict() or {}
                if link.get("attemptId") != attempt_ref.id:
                    raise FinancialConflict("Beam charge is already linked")
                return True
            transaction.create(
                charge_ref,
                {
                    "attemptId": attempt_ref.id,
                    "paymentId": str(attempt.get("paymentId", "")),
                    "providerReferenceId": charge.reference_id,
                    "createdAt": now,
                },
            )
            updates = _charge_link_attempt_updates(attempt, charge, now)
            transaction.update(attempt_ref, updates)
            return True

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment reconciliation link is unavailable") from error

    async def mark_reconciliation_missing(
        self,
        target: PaymentReconciliationTarget,
        *,
        not_before: datetime,
        now: datetime,
    ) -> None:
        attempt_ref = self._client.collection("payment_attempts").document(target.attempt_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            attempt_snapshot = await _one(transaction, attempt_ref)
            if not attempt_snapshot.exists:
                return
            attempt = attempt_snapshot.to_dict() or {}
            if (
                attempt.get("providerReferenceId") != target.provider_reference_id
                or attempt.get("paymentId") != target.payment_id
                or attempt.get("providerChargeId") is not None
                or attempt.get("status") not in _RECONCILABLE_ATTEMPT_STATUSES
            ):
                return
            expires_at = attempt.get("expiresAt")
            if (
                not isinstance(expires_at, datetime)
                or expires_at.tzinfo is None
                or expires_at.utcoffset() is None
                or expires_at + (not_before - target.expires_at) > now
            ):
                return
            payment_ref = self._client.collection("payments").document(target.payment_id)
            guard_ref = self._client.collection("payment_attempt_guards").document(
                str(attempt.get("bookingDocId", ""))
            )
            payment_snapshot = await _one(transaction, payment_ref)
            guard_snapshot = await _one(transaction, guard_ref)
            if not payment_snapshot.exists:
                raise FinancialConflict("Payment no longer exists")
            payment = _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
            transaction.update(
                attempt_ref,
                {
                    "status": PaymentAttemptStatus.FAILED,
                    "failureCode": "BEAM_CHARGE_NOT_FOUND_AFTER_EXPIRY",
                    "lastReconciledAt": now,
                    "updatedAt": now,
                    "version": int(attempt.get("version", 1)) + 1,
                },
            )
            if payment.status is not PaymentStatus.PAID:
                transaction.update(
                    payment_ref,
                    {
                        "status": PaymentStatus.DUE,
                        "activeAttemptId": None,
                        "updatedAt": now,
                        "version": payment.version + 1,
                    },
                )
            guard = guard_snapshot.to_dict() or {}
            if guard_snapshot.exists and guard.get("attemptId") == target.attempt_id:
                transaction.update(guard_ref, {"active": False, "updatedAt": now})

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment reconciliation state is unavailable") from error

    async def accept_webhook(
        self, event_id: str, event_type: str, charge_id: str, now: datetime
    ) -> bool:
        event_ref = self._client.collection("payment_webhook_events").document(event_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> bool:
            snapshot = await _one(transaction, event_ref)
            if snapshot.exists:
                return (snapshot.to_dict() or {}).get("status") != "PROCESSED"
            transaction.create(
                event_ref,
                {
                    "provider": "BEAM",
                    "eventType": event_type,
                    "providerResourceId": charge_id,
                    "status": "RECEIVED",
                    "receivedAt": now,
                    "updatedAt": now,
                },
            )
            return True

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Webhook receipt store is unavailable") from error

    async def settle_beam_charge(self, event_id: str, charge: BeamCharge, now: datetime) -> None:
        event_ref = self._client.collection("payment_webhook_events").document(event_id)
        charge_ref = self._client.collection("beam_charge_links").document(charge.charge_id)

        @async_transactional
        async def run(transaction: AsyncTransaction) -> None:
            event_snapshot = await _one(transaction, event_ref)
            charge_snapshot = await _one(transaction, charge_ref)
            if not event_snapshot.exists or not charge_snapshot.exists:
                raise FinancialConflict("Beam webhook does not match a known attempt")
            link = charge_snapshot.to_dict() or {}
            attempt_ref = self._client.collection("payment_attempts").document(
                str(link.get("attemptId", ""))
            )
            payment_ref = self._client.collection("payments").document(
                str(link.get("paymentId", ""))
            )
            attempt_snapshot = await _one(transaction, attempt_ref)
            payment_snapshot = await _one(transaction, payment_ref)
            if not attempt_snapshot.exists or not payment_snapshot.exists:
                raise FinancialConflict("Beam payment state is incomplete")
            attempt = attempt_snapshot.to_dict() or {}
            payment = _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
            booking_ref = self._client.collection("bookings").document(payment.booking_doc_id)
            guard_ref = self._client.collection("payment_attempt_guards").document(
                payment.booking_doc_id
            )
            export = None
            export_ref = None
            export_snapshot = None
            if charge.status == "SUCCEEDED":
                attempt_created_at = attempt.get("createdAt")
                attempt_expires_at_value = attempt.get("expiresAt")
                if not isinstance(attempt_created_at, datetime) or not isinstance(
                    attempt_expires_at_value, datetime
                ):
                    raise FinancialConflict("Payment attempt window is incomplete")
                export_candidate_payment = payment
                if payment.status is not PaymentStatus.PAID:
                    paid_at = validate_authoritative_charge(
                        charge,
                        payment,
                        expected_merchant_id=str(self._settings.beam_merchant_id),
                        expected_reference_id=str(attempt.get("providerReferenceId", "")),
                        attempt_created_at=attempt_created_at,
                        attempt_expires_at=attempt_expires_at_value,
                    )
                    export_candidate_payment = payment.mark_paid(
                        source=PaymentSource.BEAM,
                        paid_at=paid_at,
                        provider_resource_id=charge.charge_id,
                    )
                elif payment.provider_resource_id != charge.charge_id:
                    raise FinancialConflict("Payment has different authoritative evidence")
                export = build_accounting_export(export_candidate_payment)
                export_ref = self._client.collection("accounting_exports").document(
                    export.export_id
                )
                export_snapshot = await _one(transaction, export_ref)
            guard_snapshot = await _one(transaction, guard_ref)
            booking_snapshot = await _one(transaction, booking_ref)
            if not booking_snapshot.exists:
                raise FinancialConflict("Payment Booking no longer exists")

            if charge.status == "SUCCEEDED" and export is not None and export_ref is not None:
                paid = (
                    payment
                    if payment.status is PaymentStatus.PAID
                    else payment.mark_paid(
                        source=PaymentSource.BEAM,
                        paid_at=charge.transaction_time,  # validated above
                        provider_resource_id=charge.charge_id,
                    )
                )
                if export_snapshot is not None and export_snapshot.exists:
                    stored = export_snapshot.to_dict() or {}
                    if stored.get("paymentId") != paid.payment_id:
                        raise FinancialConflict("Accounting export conflicts with payment")
                else:
                    transaction.create(export_ref, _export_data(export, now))
                transaction.update(
                    payment_ref,
                    {**_payment_data(paid, now), "activeAttemptId": None},
                )
                transaction.update(
                    attempt_ref,
                    {
                        "status": PaymentAttemptStatus.SUCCEEDED,
                        "providerTransactionAt": charge.transaction_time,
                        "lastReconciledAt": now,
                        "updatedAt": now,
                        "version": int(attempt.get("version", 1)) + 1,
                    },
                )
                transaction.update(
                    booking_ref,
                    {
                        "paymentStatus": PaymentStatus.PAID,
                        "tipAmountSatang": paid.amounts.tip_amount_satang,
                        "grossAmountSatang": paid.amounts.gross_amount_satang,
                        "amountDueSatang": 0,
                        "paidAmountSatang": paid.amounts.gross_amount_satang,
                        "paymentUpdatedAt": now,
                    },
                )
            elif charge.status in {"FAILED", "EXPIRED", "CANCELED", "CANCELLED"}:
                if payment.status is not PaymentStatus.PAID:
                    transaction.update(
                        payment_ref,
                        {
                            "status": PaymentStatus.DUE,
                            "activeAttemptId": None,
                            "updatedAt": now,
                            "version": payment.version + 1,
                        },
                    )
                transaction.update(
                    attempt_ref,
                    {
                        "status": PaymentAttemptStatus.FAILED,
                        "lastReconciledAt": now,
                        "failureCode": charge.failure_code,
                        "updatedAt": now,
                        "version": int(attempt.get("version", 1)) + 1,
                    },
                )
            else:
                transaction.update(
                    event_ref,
                    {"status": "RECONCILE_REQUIRED", "updatedAt": now},
                )
                return
            guard = guard_snapshot.to_dict() or {}
            if guard_snapshot.exists and guard.get("attemptId") == attempt_ref.id:
                transaction.update(guard_ref, {"active": False, "updatedAt": now})
            transaction.update(
                event_ref,
                {"status": "PROCESSED", "processedAt": now, "updatedAt": now},
            )

        try:
            await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Beam settlement store is unavailable") from error

    async def resolve_status(self, status_token: str) -> PaymentStatusResult:
        token_ref = self._client.collection("payment_status_tokens").document(
            _status_token_id(status_token)
        )
        try:
            token_snapshot = await token_ref.get()
            token = token_snapshot.to_dict() or {}
            if (
                not token_snapshot.exists
                or token.get("active") is not True
                or not isinstance(token.get("expiresAt"), datetime)
                or token["expiresAt"] <= datetime.now(UTC)
            ):
                raise AuthenticationInvalid("Payment status token is invalid or expired")
            payment_snapshot = (
                await self._client.collection("payments")
                .document(str(token.get("paymentId", "")))
                .get()
            )
            if not payment_snapshot.exists:
                raise AuthenticationInvalid("Payment status token is invalid")
            return _status_result(
                _payment_from_data(payment_snapshot.id, payment_snapshot.to_dict() or {})
            )
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment status store is unavailable") from error

    async def resolve_customer_attempt(
        self, attempt_id: str, principal: LinePrincipal
    ) -> CustomerPaymentResult:
        """Resolve a result-page attempt only for its linked LINE customer.

        The attempt ID is safe to place in the provider return URL, but it is not
        treated as authorization. The verified LINE identity remains mandatory.
        """
        try:
            attempt_snapshot = await self._client.collection("payment_attempts").document(
                attempt_id
            ).get()
            attempt = attempt_snapshot.to_dict() or {}
            booking_doc_id = attempt.get("bookingDocId")
            payment_id = attempt.get("paymentId")
            if (
                not attempt_snapshot.exists
                or not isinstance(booking_doc_id, str)
                or not booking_doc_id
                or not isinstance(payment_id, str)
                or not payment_id
            ):
                raise AuthenticationInvalid("Payment attempt is unavailable")

            link_query = (
                self._client.collection("line_booking_links")
                .where(filter=FieldFilter("lineUserId", "==", principal.user_id))
                .limit(50)
            )
            links = [snapshot async for snapshot in link_query.stream()]
            if not any(
                (link.to_dict() or {}).get("bookingDocId") == booking_doc_id
                and (link.to_dict() or {}).get("channelId") == principal.channel_id
                and (link.to_dict() or {}).get("active") is True
                for link in links
            ):
                raise AuthenticationInvalid("Payment attempt is unavailable")

            payment_snapshot = await self._client.collection("payments").document(
                payment_id
            ).get()
            payment = (
                _payment_from_data(payment_snapshot.id, payment_snapshot.to_dict() or {})
                if payment_snapshot.exists
                else None
            )
            if payment is None or payment.booking_doc_id != booking_doc_id:
                raise AuthenticationInvalid("Payment attempt is unavailable")
            try:
                payment_method = BeamPaymentMethod(str(attempt.get("paymentMethod", "")))
            except ValueError as error:
                raise PersistenceUnavailable("Payment attempt method is invalid") from error
            status = _status_result(payment)
            return CustomerPaymentResult(
                attempt_id=attempt_snapshot.id,
                payment_method=payment_method,
                payment_id=status.payment_id,
                booking_id=status.booking_id,
                status=status.status,
                source=status.source,
                service_amount_satang=status.service_amount_satang,
                tip_amount_satang=status.tip_amount_satang,
                gross_amount_satang=status.gross_amount_satang,
                paid_at=status.paid_at,
            )
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Payment result store is unavailable") from error

    async def update_booking_discount(
        self,
        *,
        booking_public_id: str,
        principal: AdminPrincipal,
        discount_amount_satang: int,
        reason: str,
        expected_booking_version: int,
        now: datetime,
    ) -> BookingDiscountResult:
        @async_transactional
        async def run(transaction: AsyncTransaction) -> BookingDiscountResult:
            (
                booking_snapshot,
                booking,
                lines,
                payment_ref,
                payment_snapshot,
            ) = await self._booking_context(transaction, booking_public_id, None)
            principal.require_branch(str(booking.get("branchId", "")))
            try:
                booking_status = BookingStatus(str(booking.get("status", "")))
            except ValueError as error:
                raise PersistenceUnavailable("Booking payment state is invalid") from error
            if booking_status is not BookingStatus.COMPLETED:
                raise PaymentNotEligible(
                    "Booking discount may only be changed after service completion"
                )
            current_booking_version = int(booking.get("version", 1))
            if current_booking_version != expected_booking_version:
                raise FinancialConflict("Booking version changed; reload before trying again")
            if booking.get("paymentCorrectionHold") is True:
                raise FinancialConflict("Payment review must be resolved before changing discount")

            payment = (
                _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
                if payment_snapshot.exists
                else _new_payment(booking_snapshot.id, booking, lines)
            )
            if payment.status is not PaymentStatus.DUE:
                if payment.status is PaymentStatus.PAID:
                    raise FinancialConflict("Paid Bookings require a separate refund or correction")
                raise FinancialConflict(
                    "Payment must return to DUE before changing the Booking discount"
                )

            guard_ref = self._client.collection("payment_attempt_guards").document(
                booking_snapshot.id
            )
            guard_snapshot = await _one(transaction, guard_ref)
            guard = guard_snapshot.to_dict() or {}
            guarded_attempt: dict[str, Any] = {}
            if isinstance(guard.get("attemptId"), str):
                guarded_attempt_snapshot = await _one(
                    transaction,
                    self._client.collection("payment_attempts").document(guard["attemptId"]),
                )
                if guarded_attempt_snapshot.exists:
                    guarded_attempt = guarded_attempt_snapshot.to_dict() or {}
            if (
                guard.get("active") is True
                and isinstance(guard.get("expiresAt"), datetime)
                and guard["expiresAt"] > now
            ):
                raise FinancialConflict("An active Beam attempt exists")
            if guarded_attempt.get("status") in {
                PaymentAttemptStatus.CREATING,
                PaymentAttemptStatus.CREATE_UNKNOWN,
                PaymentAttemptStatus.ACTIVE,
                PaymentAttemptStatus.PAYMENT_REVIEW,
            }:
                raise FinancialConflict("Beam attempt reconciliation is required")

            normalized_reason = validate_fixed_discount(
                subtotal_amount_satang=int(payment.subtotal_amount_satang or 0),
                discount_amount_satang=discount_amount_satang,
                reason=reason,
            )
            old_discount = int(booking.get("discountAmountSatang", 0))
            old_reason = str(booking.get("discountReason") or "") or None
            stored_reason = normalized_reason if discount_amount_satang else None
            updated_payment = _with_discount(
                payment,
                discount_amount_satang=discount_amount_satang,
                reason=normalized_reason,
            )
            next_booking_version = current_booking_version + 1
            settlement_ref = self._client.collection("service_settlements").document(
                booking_snapshot.id
            )
            settlement_snapshot = await _one(transaction, settlement_ref)
            settlement_stale = settlement_snapshot.exists
            booking_update: dict[str, Any] = {
                "discountAmountSatang": discount_amount_satang,
                "discountType": "ADMIN_FIXED" if discount_amount_satang else None,
                "discountReason": stored_reason,
                "discountAppliedBy": principal.uid if discount_amount_satang else None,
                "discountAppliedAt": now if discount_amount_satang else None,
                "estimatedAmountSatang": updated_payment.amounts.service_amount_satang,
                "tipAmountSatang": updated_payment.amounts.tip_amount_satang,
                "grossAmountSatang": updated_payment.amounts.gross_amount_satang,
                "amountDueSatang": updated_payment.amounts.gross_amount_satang,
                "paymentStatus": PaymentStatus.DUE,
                "paidAmountSatang": 0,
                "paymentUpdatedAt": now,
                "version": next_booking_version,
                "updatedAt": now,
            }
            if settlement_stale:
                booking_update.update(
                    {
                        "financialSettlementStatus": "STALE",
                        "financialSettlementUpdatedAt": now,
                    }
                )
            transaction.update(booking_snapshot.reference, booking_update)
            if payment_snapshot.exists:
                transaction.update(payment_ref, _payment_data(updated_payment, now))
            else:
                transaction.create(
                    payment_ref,
                    {**_payment_data(updated_payment, now), "createdAt": now},
                )

            event_type = (
                "BOOKING_DISCOUNT_APPLIED"
                if old_discount == 0 and discount_amount_satang > 0
                else "BOOKING_DISCOUNT_REMOVED"
                if old_discount > 0 and discount_amount_satang == 0
                else "BOOKING_DISCOUNT_UPDATED"
            )
            transaction.create(
                self._client.collection("audit_events").document(uuid4().hex),
                {
                    "eventType": event_type,
                    "actorType": "ADMIN_USER",
                    "actorId": principal.uid,
                    "branchId": updated_payment.branch_id,
                    "bookingDocId": updated_payment.booking_doc_id,
                    "publicBookingId": booking_public_id,
                    "paymentId": updated_payment.payment_id,
                    "subtotalAmountSatang": updated_payment.subtotal_amount_satang,
                    "oldDiscountAmountSatang": old_discount,
                    "newDiscountAmountSatang": discount_amount_satang,
                    "oldDiscountReason": old_reason,
                    "discountReason": normalized_reason,
                    "oldServiceAmountSatang": payment.amounts.service_amount_satang,
                    "newServiceAmountSatang": updated_payment.amounts.service_amount_satang,
                    "bookingVersion": next_booking_version,
                    "paymentVersion": updated_payment.version,
                    "settlementMarkedStale": settlement_stale,
                    "occurredAt": now,
                    "createdAt": now,
                },
            )
            return BookingDiscountResult(
                booking_id=booking_public_id,
                booking_version=next_booking_version,
                subtotal_amount_satang=int(updated_payment.subtotal_amount_satang or 0),
                discount_amount_satang=discount_amount_satang,
                discount_reason=stored_reason,
                service_amount_satang=updated_payment.amounts.service_amount_satang,
                tip_amount_satang=updated_payment.amounts.tip_amount_satang,
                gross_amount_satang=updated_payment.amounts.gross_amount_satang,
                payment_status=updated_payment.status,
                payment_version=updated_payment.version,
                settlement_stale=settlement_stale,
            )

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Booking discount store is unavailable") from error

    async def record_cash(
        self,
        *,
        booking_public_id: str,
        principal: AdminPrincipal,
        tip_amount_satang: int,
        expected_version: int,
        idempotency_key: str,
        now: datetime,
    ) -> PaymentStatusResult:
        idem_ref = self._client.collection("idempotency_records").document(
            _idempotency_id(f"cash:{principal.uid}:{booking_public_id}", idempotency_key)
        )

        @async_transactional
        async def run(transaction: AsyncTransaction) -> PaymentStatusResult:
            idem_snapshot = await _one(transaction, idem_ref)
            if idem_snapshot.exists:
                response = (idem_snapshot.to_dict() or {}).get("response")
                if not isinstance(response, dict) or int(response.get("tipAmountSatang", -1)) != (
                    tip_amount_satang
                ):
                    raise FinancialConflict("Cash idempotency key conflicts")
                return PaymentStatusResult(
                    payment_id=str(response["paymentId"]),
                    booking_id=str(response["bookingId"]),
                    status=PaymentStatus(response["status"]),
                    source=PaymentSource(response["source"]),
                    service_amount_satang=int(response["serviceAmountSatang"]),
                    tip_amount_satang=int(response["tipAmountSatang"]),
                    gross_amount_satang=int(response["grossAmountSatang"]),
                    paid_at=response["paidAt"],
                )
            (
                booking_snapshot,
                booking,
                lines,
                payment_ref,
                payment_snapshot,
            ) = await self._booking_context(transaction, booking_public_id, None)
            principal.require_branch(str(booking.get("branchId", "")))
            if BookingStatus(booking.get("status")) is not BookingStatus.COMPLETED:
                raise PaymentNotEligible("Booking must be completed before recording cash")
            payment = (
                _payment_from_data(payment_ref.id, payment_snapshot.to_dict() or {})
                if payment_snapshot.exists
                else _new_payment(booking_snapshot.id, booking, lines)
            )
            if payment.status is PaymentStatus.PAID:
                if (
                    payment.source is PaymentSource.CASH
                    and payment.cash_received_by == principal.uid
                ):
                    return _status_result(payment)
                raise FinancialConflict("Payment is already paid")
            if payment.version != expected_version:
                raise FinancialConflict("Payment version changed")
            payment = _with_tip(payment, tip_amount_satang)
            paid = payment.mark_paid(
                source=PaymentSource.CASH,
                paid_at=now,
                cash_received_by=principal.uid,
            )
            export = build_accounting_export(paid)
            export_ref = self._client.collection("accounting_exports").document(export.export_id)
            export_snapshot = await _one(transaction, export_ref)
            if (
                export_snapshot.exists
                and (export_snapshot.to_dict() or {}).get("paymentId") != paid.payment_id
            ):
                raise FinancialConflict("Accounting export conflicts with cash payment")
            guard_ref = self._client.collection("payment_attempt_guards").document(
                booking_snapshot.id
            )
            guard_snapshot = await _one(transaction, guard_ref)
            guard = guard_snapshot.to_dict() or {}
            guarded_attempt: dict[str, Any] = {}
            if isinstance(guard.get("attemptId"), str):
                guarded_attempt_snapshot = await _one(
                    transaction,
                    self._client.collection("payment_attempts").document(guard["attemptId"]),
                )
                if guarded_attempt_snapshot.exists:
                    guarded_attempt = guarded_attempt_snapshot.to_dict() or {}
            if (
                guard.get("active") is True
                and isinstance(guard.get("expiresAt"), datetime)
                and guard["expiresAt"] > now
            ):
                raise FinancialConflict("An active Beam attempt exists")
            if guarded_attempt.get("status") in {
                PaymentAttemptStatus.CREATING,
                PaymentAttemptStatus.CREATE_UNKNOWN,
                PaymentAttemptStatus.ACTIVE,
                PaymentAttemptStatus.PAYMENT_REVIEW,
            }:
                raise FinancialConflict("Beam attempt reconciliation is required")
            result = _status_result(paid)
            if payment_snapshot.exists:
                transaction.update(
                    payment_ref,
                    {**_payment_data(paid, now), "activeAttemptId": None},
                )
            else:
                transaction.create(payment_ref, {**_payment_data(paid, now), "createdAt": now})
            if not export_snapshot.exists:
                transaction.create(export_ref, _export_data(export, now))
            transaction.update(
                booking_snapshot.reference,
                {
                    "paymentStatus": PaymentStatus.PAID,
                    "tipAmountSatang": paid.amounts.tip_amount_satang,
                    "grossAmountSatang": paid.amounts.gross_amount_satang,
                    "amountDueSatang": 0,
                    "paidAmountSatang": paid.amounts.gross_amount_satang,
                    "paymentUpdatedAt": now,
                },
            )
            transaction.create(
                self._client.collection("audit_events").document(uuid4().hex),
                {
                    "eventType": "CASH_PAYMENT_RECORDED",
                    "actorType": "ADMIN_USER",
                    "actorId": principal.uid,
                    "branchId": paid.branch_id,
                    "bookingDocId": paid.booking_doc_id,
                    "paymentId": paid.payment_id,
                    "occurredAt": now,
                    "createdAt": now,
                },
            )
            transaction.create(
                idem_ref,
                {
                    "scope": "CASH_PAYMENT_RECORD",
                    "response": {
                        **asdict(result),
                        "paymentId": result.payment_id,
                        "bookingId": result.booking_id,
                        "serviceAmountSatang": result.service_amount_satang,
                        "tipAmountSatang": result.tip_amount_satang,
                        "grossAmountSatang": result.gross_amount_satang,
                        "paidAt": result.paid_at,
                    },
                    "expiresAt": now + timedelta(hours=self._settings.idempotency_ttl_hours),
                    "createdAt": now,
                },
            )
            return result

        try:
            return await run(self._client.transaction())
        except GoogleAPICallError as error:
            raise PersistenceUnavailable("Cash payment store is unavailable") from error
