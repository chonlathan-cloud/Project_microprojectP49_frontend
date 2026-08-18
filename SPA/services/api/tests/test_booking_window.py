from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import AdvanceWindowViolation
from app.domains.bookings.service import _validate_advance_window

TZ = ZoneInfo("Asia/Bangkok")
BRANCH = {"bookingWindow": {"minDays": 1, "maxDays": 30}}


def test_booking_window_uses_branch_local_calendar_days() -> None:
    _validate_advance_window(
        datetime(2026, 8, 19, 10, 0, tzinfo=TZ),
        BRANCH,
        today=date(2026, 8, 18),
    )
    _validate_advance_window(
        datetime(2026, 9, 17, 20, 0, tzinfo=TZ),
        BRANCH,
        today=date(2026, 8, 18),
    )


@pytest.mark.parametrize("local_date", [date(2026, 8, 18), date(2026, 9, 18)])
def test_booking_window_rejects_dates_outside_branch_configuration(local_date: date) -> None:
    with pytest.raises(AdvanceWindowViolation) as error:
        _validate_advance_window(
            datetime.combine(local_date, datetime.min.time(), TZ),
            BRANCH,
            today=date(2026, 8, 18),
        )

    assert error.value.code == "ADVANCE_WINDOW_VIOLATION"
