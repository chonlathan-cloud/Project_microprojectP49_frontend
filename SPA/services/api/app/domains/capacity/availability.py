from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.domains.bookings.plan import capacity_bucket_demands
from app.domains.bookings.service import _bucket_id

TZ = ZoneInfo("Asia/Bangkok")


def search_capacity_slots(
    client: firestore.Client,
    *,
    branch_id: str,
    date_from: str,
    date_to: str,
    duration_minutes: int | None = None,
    units: int | None = None,
    participant_duration_minutes: list[int] | None = None,
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
    durations = participant_duration_minutes or (
        [duration_minutes] * units
        if duration_minutes is not None and units is not None and units > 0
        else []
    )
    if not durations or any(item <= 0 for item in durations):
        return availability_response(branch_id, [], "INVALID_PARTICIPANT_CONFIGURATION")
    booking_duration = max(durations)

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
            while cursor + timedelta(minutes=booking_duration) <= closing:
                if mode == "PUBLIC" and cursor <= now + timedelta(days=min_days):
                    cursor += timedelta(minutes=15)
                    continue
                if mode == "ADMIN" and cursor < current_bucket:
                    cursor += timedelta(minutes=15)
                    continue
                demands = capacity_bucket_demands(
                    cursor,
                    durations,
                    int(branch.get("bufferMinutes", 0)),
                )
                bucket_snapshots = {
                    bucket_start: client.collection("capacity_buckets")
                    .document(_bucket_id(branch_id, bucket_start))
                    .get()
                    for bucket_start in demands
                }
                available = min(
                    capacity
                    - (
                        int((snapshot.to_dict() or {}).get("usedUnits", 0))
                        if snapshot.exists
                        else 0
                    )
                    for snapshot in bucket_snapshots.values()
                )
                if all(
                    capacity
                    - (
                        int((bucket_snapshots[bucket_start].to_dict() or {}).get("usedUnits", 0))
                        if bucket_snapshots[bucket_start].exists
                        else 0
                    )
                    >= demand
                    for bucket_start, demand in demands.items()
                ):
                    slots.append(
                        {
                            "localDate": day.isoformat(),
                            "localStartTime": cursor.strftime("%H:%M"),
                            "availableUnits": available,
                        }
                    )
                cursor += timedelta(minutes=15)
        day += timedelta(days=1)
    return availability_response(branch_id, slots, "READY" if slots else "CAPACITY_UNAVAILABLE")


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
