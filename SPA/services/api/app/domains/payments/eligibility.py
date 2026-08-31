from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import PaymentNotEligible
from app.core.types import BookingStatus, PaymentStatus

BANGKOK = ZoneInfo("Asia/Bangkok")
ATTEMPT_TTL = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class PaymentEligibility:
    eligible: bool
    reason: str | None


def evaluate_payment_eligibility(
    *,
    booking_status: BookingStatus,
    booking_local_date: date,
    payment_status: PaymentStatus,
    amount_due_satang: int,
    has_unexpired_attempt: bool,
    on_correction_hold: bool,
    now: datetime,
    late_override_until: datetime | None = None,
) -> PaymentEligibility:
    if now.tzinfo is None or now.utcoffset() is None:
        raise PaymentNotEligible("Server time must be timezone-aware")
    if booking_status is not BookingStatus.COMPLETED:
        return PaymentEligibility(False, "BOOKING_NOT_COMPLETED")
    if amount_due_satang <= 0 or payment_status is PaymentStatus.PAID:
        return PaymentEligibility(False, "NOTHING_DUE")
    if (
        payment_status
        in {
            PaymentStatus.PAYMENT_REVIEW,
            PaymentStatus.REFUND_PENDING,
            PaymentStatus.PARTIALLY_REFUNDED,
            PaymentStatus.REFUNDED,
        }
        or on_correction_hold
    ):
        return PaymentEligibility(False, "PAYMENT_REVIEW_REQUIRED")
    if has_unexpired_attempt:
        return PaymentEligibility(False, "ACTIVE_ATTEMPT_EXISTS")

    local_now = now.astimezone(BANGKOK)
    has_late_override = (
        late_override_until is not None
        and late_override_until.tzinfo is not None
        and late_override_until >= now
    )
    if local_now.date() != booking_local_date and not has_late_override:
        return PaymentEligibility(False, "OUTSIDE_SERVICE_DATE")
    return PaymentEligibility(True, None)


def require_payment_eligibility(**kwargs: object) -> None:
    result = evaluate_payment_eligibility(**kwargs)  # type: ignore[arg-type]
    if not result.eligible:
        raise PaymentNotEligible(result.reason or "Payment is unavailable")


def attempt_expires_at(created_at: datetime) -> datetime:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise PaymentNotEligible("Attempt creation time must be timezone-aware")
    return created_at + ATTEMPT_TTL
