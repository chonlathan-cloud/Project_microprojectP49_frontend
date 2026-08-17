import pytest

from app.core.errors import InvalidStateTransition
from app.core.types import BookingStatus
from app.domains.bookings.state_machine import BookingStateMachine


def test_pending_can_be_confirmed() -> None:
    assert (
        BookingStateMachine.transition(BookingStatus.PENDING, "confirm") is BookingStatus.CONFIRMED
    )


def test_start_requires_every_therapist_assignment() -> None:
    with pytest.raises(InvalidStateTransition, match="therapist"):
        BookingStateMachine.transition(BookingStatus.CONFIRMED, "start")
    assert (
        BookingStateMachine.transition(
            BookingStatus.CONFIRMED,
            "start",
            all_therapists_assigned=True,
        )
        is BookingStatus.IN_SERVICE
    )


def test_terminal_status_cannot_transition() -> None:
    with pytest.raises(InvalidStateTransition):
        BookingStateMachine.transition(BookingStatus.COMPLETED, "confirm")


def test_cancellation_requires_reason() -> None:
    with pytest.raises(InvalidStateTransition, match="reason"):
        BookingStateMachine.transition(BookingStatus.PENDING, "cancel")


def test_no_show_requires_fifteen_minute_gate_from_caller() -> None:
    with pytest.raises(InvalidStateTransition, match="threshold"):
        BookingStateMachine.transition(BookingStatus.CONFIRMED, "no_show")
    assert (
        BookingStateMachine.transition(
            BookingStatus.CONFIRMED,
            "no_show",
            no_show_window_reached=True,
        )
        is BookingStatus.NO_SHOW
    )
