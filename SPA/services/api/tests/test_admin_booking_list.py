from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1 import bookings
from app.core.auth import require_admin_user
from app.infrastructure.firestore import get_firestore_client
from app.main import app


class Snapshot:
    def __init__(self, document_id: str, data: dict[str, object]) -> None:
        self.id = document_id
        self._data = data

    def to_dict(self) -> dict[str, object]:
        return dict(self._data)


class AggregationResult:
    def __init__(self, value: int) -> None:
        self.value = value


class CountQuery:
    def __init__(self, query: Query) -> None:
        self.query = query

    def get(self):
        return [[AggregationResult(len(self.query.filtered_snapshots()))]]


class Query:
    def __init__(
        self,
        snapshots: list[Snapshot],
        *,
        filters: list[tuple[str, object]] | None = None,
        cursor: list[object] | None = None,
        limit_value: int | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.filters = filters or []
        self.cursor = cursor
        self.limit_value = limit_value

    def clone(self, **changes: object) -> Query:
        return Query(
            self.snapshots,
            filters=changes.get("filters", list(self.filters)),  # type: ignore[arg-type]
            cursor=changes.get("cursor", self.cursor),  # type: ignore[arg-type]
            limit_value=changes.get("limit_value", self.limit_value),  # type: ignore[arg-type]
        )

    def where(self, field: str, operator: str, value: object):
        assert operator == "=="
        return self.clone(filters=[*self.filters, (field, value)])

    def order_by(self, *_args, **_kwargs):
        return self.clone()

    def start_after(self, cursor: list[object]):
        return self.clone(cursor=cursor)

    def limit(self, value: int):
        return self.clone(limit_value=value)

    def count(self, alias: str):
        assert alias == "count"
        return CountQuery(self)

    def filtered_snapshots(self) -> list[Snapshot]:
        result = []
        for snapshot in self.snapshots:
            data = snapshot.to_dict()
            if all(data.get(field) == value for field, value in self.filters):
                result.append(snapshot)
        result.sort(
            key=lambda snapshot: (snapshot.to_dict()["startAt"], snapshot.id),
            reverse=True,
        )
        if self.cursor:
            cursor_key = (self.cursor[0], self.cursor[1])
            result = [
                snapshot
                for snapshot in result
                if (snapshot.to_dict()["startAt"], snapshot.id) < cursor_key
            ]
        return result

    def stream(self):
        result = self.filtered_snapshots()
        return iter(result[: self.limit_value] if self.limit_value else result)


class Database:
    def __init__(self, snapshots: list[Snapshot]) -> None:
        self.snapshots = snapshots

    def collection(self, name: str) -> Query:
        assert name == "bookings"
        return Query(self.snapshots)


class DetailQuery:
    def __init__(
        self,
        snapshots: list[Snapshot],
        filters: list[tuple[str, object]] | None = None,
        limit_value: int | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.filters = filters or []
        self.limit_value = limit_value

    def where(self, field: str, operator: str, value: object) -> DetailQuery:
        assert operator == "=="
        return DetailQuery(self.snapshots, [*self.filters, (field, value)], self.limit_value)

    def limit(self, value: int) -> DetailQuery:
        return DetailQuery(self.snapshots, list(self.filters), value)

    def stream(self):
        matches = [
            snapshot
            for snapshot in self.snapshots
            if all(snapshot.to_dict().get(field) == value for field, value in self.filters)
        ]
        return iter(matches[: self.limit_value] if self.limit_value else matches)


class DetailDatabase:
    def __init__(self) -> None:
        start_at = datetime(2026, 9, 2, 3, tzinfo=UTC)
        self.collections = {
            "bookings": [
                Snapshot(
                    "booking-doc-1",
                    {
                        "publicBookingId": "BK-DETAIL",
                        "branchId": "branch_001",
                        "status": "CONFIRMED",
                        "startAt": start_at,
                        "endAt": start_at.replace(hour=4),
                        "customerName": "Customer",
                        "contact": {
                            "phoneMasked": "081 *** 5678",
                            "phoneE164": "+66812345678",
                        },
                        "serviceName": "Thai Massage",
                        "pax": 2,
                        "therapistIds": ["therapist-1", "therapist-2"],
                        "version": 3,
                    },
                )
            ],
            "booking_participants": [
                Snapshot(
                    "participant-2",
                    {
                        "bookingDocId": "booking-doc-1",
                        "sequence": 2,
                        "nickname": "Guest two",
                        "healthProfileId": "private-health-2",
                    },
                ),
                Snapshot(
                    "participant-1",
                    {
                        "bookingDocId": "booking-doc-1",
                        "sequence": 1,
                        "nickname": "Guest one",
                        "healthProfileId": "private-health-1",
                    },
                ),
            ],
            "booking_line_items": [
                Snapshot(
                    "line-1",
                    {
                        "bookingDocId": "booking-doc-1",
                        "participantIds": ["participant-1", "participant-2"],
                        "serviceSnapshot": {
                            "nameTh": "นวดแผนไทย",
                            "nameEn": "Thai massage",
                            "durationMinutes": 60,
                        },
                    },
                )
            ],
        }

    def collection(self, name: str) -> DetailQuery:
        return DetailQuery(self.collections[name])


def settings():
    return type(
        "Settings",
        (),
        {"line_customer_messaging_channel_secret": "test-cursor-secret"},
    )()


def booking(
    document_id: str,
    day: int,
    status: str,
    *,
    customer_name: str,
    assignment_state: str = "ASSIGNED",
) -> Snapshot:
    start_at = datetime(2026, 9, day, 3, tzinfo=UTC)
    return Snapshot(
        document_id,
        {
            "publicBookingId": f"BK-{document_id.upper()}",
            "branchId": "branch_001",
            "status": status,
            "assignmentState": assignment_state,
            "startAt": start_at,
            "endAt": start_at.replace(hour=4),
            "customerName": customer_name,
            "contact": {
                "phoneMasked": "081 *** 5678",
                "phoneE164": "+66812345678",
            },
            "serviceName": "Thai Massage",
            "pax": 1,
        },
    )


def get(path: str, database: object, monkeypatch) -> TestClient:
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "admin-001",
        "role": "ADMIN",
    }
    app.dependency_overrides[get_firestore_client] = lambda: database
    monkeypatch.setattr(bookings, "get_settings", settings)
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.pop(require_admin_user, None)
    app.dependency_overrides.pop(get_firestore_client, None)


def test_admin_booking_list_is_newest_first_and_cursor_paginated(monkeypatch) -> None:
    database = Database(
        [
            booking("d1", 1, "CONFIRMED", customer_name="One"),
            booking("d4", 4, "PENDING", customer_name="Four"),
            booking(
                "d3",
                4,
                "CONFIRMED",
                customer_name="Pinyada",
                assignment_state="UNASSIGNED",
            ),
            booking("d2", 2, "PENDING", customer_name="Two"),
        ]
    )
    client = get("/api/v1/admin/bookings", database, monkeypatch)
    try:
        first = client.get("/api/v1/admin/bookings?pageSize=2")
        assert first.status_code == 200
        first_payload = first.json()
        assert [item["bookingId"] for item in first_payload["items"]] == [
            "BK-D4",
            "BK-D3",
        ]
        assert first_payload["summary"] == {"pending": 2, "unassigned": 1}
        assert first_payload["hasMore"] is True

        second = client.get(
            "/api/v1/admin/bookings",
            params={"pageSize": 2, "pageToken": first_payload["nextPageToken"]},
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert [item["bookingId"] for item in second_payload["items"]] == [
            "BK-D2",
            "BK-D1",
        ]
        assert second_payload["hasMore"] is False
    finally:
        clear_overrides()


def test_admin_booking_filter_search_and_cursor_scope(monkeypatch) -> None:
    database = Database(
        [
            booking("d4", 4, "PENDING", customer_name="Four"),
            booking("d3", 3, "CONFIRMED", customer_name="Pinyada"),
            booking("d2", 2, "PENDING", customer_name="Two"),
        ]
    )
    client = get("/api/v1/admin/bookings", database, monkeypatch)
    try:
        filtered = client.get(
            "/api/v1/admin/bookings",
            params={"status": "PENDING", "pageSize": 1},
        )
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert [item["bookingId"] for item in filtered_payload["items"]] == ["BK-D4"]

        search = client.get(
            "/api/v1/admin/bookings",
            params={"search": "pinyada"},
        )
        assert search.status_code == 200
        assert [item["bookingId"] for item in search.json()["items"]] == ["BK-D3"]

        mismatched = client.get(
            "/api/v1/admin/bookings",
            params={
                "status": "CONFIRMED",
                "pageSize": 1,
                "pageToken": filtered_payload["nextPageToken"],
            },
        )
        assert mismatched.status_code == 422
        assert mismatched.json()["detail"] == "Invalid Admin booking page token"
    finally:
        clear_overrides()


def test_admin_booking_detail_maps_participants_without_health_or_full_phone(monkeypatch) -> None:
    database = DetailDatabase()
    client = get("/api/v1/admin/bookings/BK-DETAIL", database, monkeypatch)
    try:
        response = client.get("/api/v1/admin/bookings/BK-DETAIL")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["customerPhoneMasked"] == "081 *** 5678"
    assert "contact" not in payload
    assert [item["nickname"] for item in payload["participants"]] == [
        "Guest one",
        "Guest two",
    ]
    assert [item["therapistId"] for item in payload["participants"]] == [
        "therapist-1",
        "therapist-2",
    ]
    assert all("healthProfileId" not in item for item in payload["participants"])
