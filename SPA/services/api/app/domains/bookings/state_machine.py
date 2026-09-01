from app.core.errors import InvalidStateTransition
from app.core.types import BookingStatus


class BookingStateMachine:
    _transitions = {
        (BookingStatus.PENDING, "CONFIRM"): BookingStatus.CONFIRMED,
        (BookingStatus.PENDING, "CANCEL"): BookingStatus.CANCELLED,
        (BookingStatus.CONFIRMED, "START"): BookingStatus.IN_SERVICE,
        (BookingStatus.CONFIRMED, "CANCEL"): BookingStatus.CANCELLED,
        (BookingStatus.CONFIRMED, "NO_SHOW"): BookingStatus.NO_SHOW,
        (BookingStatus.IN_SERVICE, "COMPLETE"): BookingStatus.COMPLETED,
        (BookingStatus.RECORDED, "CANCEL"): BookingStatus.CANCELLED,
    }

    @classmethod
    def transition(
        cls,
        current: BookingStatus,
        command: str,
        *,
        cancellation_reason: str | None = None,
        all_therapists_assigned: bool = False,
        no_show_window_reached: bool = False,
    ) -> BookingStatus:
        normalized_command = command.upper()
        target = cls._transitions.get((current, normalized_command))
        if target is None:
            raise InvalidStateTransition(f"Cannot {normalized_command} a {current} booking")
        if normalized_command == "CANCEL" and not cancellation_reason:
            raise InvalidStateTransition("Cancellation requires a reason")
        if normalized_command == "START" and not all_therapists_assigned:
            raise InvalidStateTransition(
                "Every participant needs a therapist before service starts"
            )
        if normalized_command == "NO_SHOW" and not no_show_window_reached:
            raise InvalidStateTransition("No-show is unavailable before the appointment threshold")
        return target
