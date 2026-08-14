from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domains.capacity.buckets import required_bucket_starts


def test_ninety_minutes_plus_buffer_uses_seven_buckets() -> None:
    start = datetime(2026, 8, 15, 14, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
    buckets = required_bucket_starts(start, 90, 15)
    assert len(buckets) == 7
    assert buckets[-1].strftime("%H:%M") == "15:30"


def test_bucket_start_must_be_aligned_in_branch_time() -> None:
    start = datetime(2026, 8, 15, 14, 5, tzinfo=ZoneInfo("Asia/Bangkok"))
    with pytest.raises(ValueError, match="align"):
        required_bucket_starts(start, 60, 0)
