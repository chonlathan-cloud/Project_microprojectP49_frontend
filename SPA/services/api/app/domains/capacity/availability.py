from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.domains.bookings.service import _bucket_id
from app.domains.capacity.buckets import required_bucket_starts

TZ = ZoneInfo("Asia/Bangkok")


def search_capacity_slots(
    client: firestore.Client,
    *,
    branch_id: str,
    date_from: str,
    date_to: str,
    duration_minutes: int,
    units: int,
    mode: str,
) -> dict[str, object]:
    branch_snapshot = client.collection("branches").document(branch_id).get()
    if not branch_snapshot.exists:
        return availability_response(branch_id, [], "RESOURCE_CONFIGURATION_REQUIRED")
    branch = branch_snapshot.to_dict() or {}
    capacity = int(branch.get("activeCapacityUnits", branch.get("capacityUnits", 0)))
    if capacity <= 0:
        return availability_response(branch_id, [], "RESOURCE_CONFIGURATION_REQUIRED")
    try:
        day_from, day_to = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        return availability_response(branch_id, [], "INVALID_DATE_RANGE")
    if day_to < day_from or (day_to - day_from).days > 31:
        return availability_response(branch_id, [], "INVALID_DATE_RANGE")
    if mode not in {"PUBLIC", "ADMIN"}:
        return availability_response(branch_id, [], "INVALID_AVAILABILITY_MODE")

    now = datetime.now(TZ)
    current_bucket = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    min_days = int((branch.get("bookingWindow") or {}).get("minDays", 1))
    slots: list[dict[str, object]] = []
    day = day_from
    while day <= day_to:
        closure = list(
            client.collection("special_closures")
            .where("branchId", "==", branch_id)
            .where("localDate", "==", day.isoformat())
            .limit(1)
            .stream()
        )
        if not closure:
            hours = (branch.get("operatingHours") or {}).get(
                str(day.weekday()), {"open": "10:00", "close": "22:00"}
            )
            open_time = time.fromisoformat(str(hours.get("open", "10:00")))
            close_time = time.fromisoformat(str(hours.get("close", "22:00")))
            cursor = datetime.combine(day, open_time, TZ)
            closing = datetime.combine(day, close_time, TZ)
            while cursor + timedelta(minutes=duration_minutes) <= closing:
                if mode == "PUBLIC" and cursor <= now + timedelta(days=min_days):
                    cursor += timedelta(minutes=15)
                    continue
                if mode == "ADMIN" and cursor < current_bucket:
                    cursor += timedelta(minutes=15)
                    continue
                bucket_starts = required_bucket_starts(
                    cursor,
                    duration_minutes,
                    int(branch.get("bufferMinutes", 0)),
                )
                bucket_snapshots = [
                    client.collection("capacity_buckets")
                    .document(_bucket_id(branch_id, item))
                    .get()
                    for item in bucket_starts
                ]
                available = min(
                    capacity - int((snapshot.to_dict() or {}).get("usedUnits", 0))
                    if snapshot.exists
                    else capacity
                    for snapshot in bucket_snapshots
                )
                if available >= units:
                    slots.append(
                        {
                            "localDate": day.isoformat(),
                            "localStartTime": cursor.strftime("%H:%M"),
                            "availableUnits": available,
                        }
                    )
                cursor += timedelta(minutes=15)
        day += timedelta(days=1)
    return availability_response(
        branch_id, slots, "READY" if slots else "CAPACITY_UNAVAILABLE"
    )


def availability_response(
    branch_id: str,
    slots: list[dict[str, object]],
    state: str,
) -> dict[str, object]:
    return {
        "branchId": branch_id,
        "timezone": "Asia/Bangkok",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "slots": slots,
        "configurationState": state,
    }
