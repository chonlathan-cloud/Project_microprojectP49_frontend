from datetime import datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo

BUCKET_MINUTES = 15


def required_bucket_starts(
    start_at: datetime,
    duration_minutes: int,
    buffer_minutes: int,
    *,
    timezone: str = "Asia/Bangkok",
) -> list[datetime]:
    if start_at.tzinfo is None:
        raise ValueError("start_at must be timezone-aware")
    if duration_minutes <= 0 or buffer_minutes < 0:
        raise ValueError("duration must be positive and buffer must be non-negative")

    local_start = start_at.astimezone(ZoneInfo(timezone))
    if local_start.minute % BUCKET_MINUTES or local_start.second or local_start.microsecond:
        raise ValueError("start_at must align to a 15-minute branch-local bucket")

    bucket_count = ceil((duration_minutes + buffer_minutes) / BUCKET_MINUTES)
    return [start_at + timedelta(minutes=index * BUCKET_MINUTES) for index in range(bucket_count)]
