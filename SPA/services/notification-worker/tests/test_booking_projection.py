from __future__ import annotations

from typing import Any

from app.main import _booking_view
from app.templates.booking import AdminNotificationBookingView, NotificationBookingView


class FakeSnapshot:
    def __init__(self, document_id: str, data: dict[str, object], *, exists: bool = True) -> None:
        self.id = document_id
        self._data = data
        self.exists = exists

    def to_dict(self) -> dict[str, object]:
        return self._data

    def get(self) -> FakeSnapshot:
        return self


class FakeQuery:
    def __init__(self, snapshots: list[FakeSnapshot]) -> None:
        self._snapshots = snapshots

    def where(self, *_args: object, **_kwargs: object) -> FakeQuery:
        return self

    def stream(self) -> list[FakeSnapshot]:
        return self._snapshots


class FakeCollection(FakeQuery):
    def __init__(
        self,
        snapshots: list[FakeSnapshot],
        documents: dict[str, FakeSnapshot] | None = None,
    ) -> None:
        super().__init__(snapshots)
        self._documents = documents or {}

    def document(self, document_id: str) -> FakeSnapshot:
        return self._documents.get(document_id, FakeSnapshot(document_id, {}, exists=False))


class FakeClient:
    def __init__(self) -> None:
        self._collections = {
            "booking_participants": FakeCollection(
                [
                    FakeSnapshot(
                        "participant-1",
                        {
                            "nickname": "Som",
                            "sequence": 1,
                            "healthAlert": True,
                            "healthProfileId": "health-1",
                        },
                    )
                ]
            ),
            "booking_line_items": FakeCollection(
                [
                    FakeSnapshot(
                        "line-1",
                        {
                            "participantIds": ["participant-1"],
                            "serviceSnapshot": {
                                "nameTh": "นวดน้ำมันอโรม่า",
                                "durationMinutes": 60,
                            },
                        },
                    )
                ]
            ),
            "health_profiles": FakeCollection(
                [],
                {
                    "health-1": FakeSnapshot(
                        "health-1",
                        {
                            "hasInformation": True,
                            "details": "แพ้น้ำมันลาเวนเดอร์",
                        },
                    )
                },
            ),
            "branches": FakeCollection(
                [],
                {
                    "branch_001": FakeSnapshot(
                        "branch_001",
                        {
                            "name": "SPA 49",
                            "address": "53/72 ถนนเฉลิมพระเกียรติ ร.9 กรุงเทพฯ 10250",
                            "mapUrl": "https://maps.example/spa49",
                        },
                    )
                },
            ),
        }

    def collection(self, name: str) -> Any:
        return self._collections[name]


def booking() -> dict[str, object]:
    return {
        "publicBookingId": "BK-TEST-001",
        "status": "PENDING",
        "customerName": "Som",
        "contact": {"phoneE164": "+66812345678"},
        "localDate": "2026-08-20",
        "localStartTime": "16:00",
        "pax": 1,
        "estimatedAmountSatang": 60000,
        "healthAlert": True,
        "branchId": "branch_001",
    }


def test_admin_projection_joins_participant_health_detail() -> None:
    view = _booking_view(
        FakeClient(),
        booking_doc_id="booking-1",
        booking=booking(),
        admin=True,
        include_health_details=True,  # type: ignore[arg-type]
    )
    assert isinstance(view, AdminNotificationBookingView)
    assert view.participants[0].has_health_information is True
    assert view.participants[0].health_details == "แพ้น้ำมันลาเวนเดอร์"


def test_customer_projection_does_not_join_participant_health_detail() -> None:
    view = _booking_view(
        FakeClient(), booking_doc_id="booking-1", booking=booking(), admin=False  # type: ignore[arg-type]
    )
    assert type(view) is NotificationBookingView
    assert "health_details" not in view.model_dump_json()
    assert "แพ้น้ำมันลาเวนเดอร์" not in view.model_dump_json()
    assert view.branch_name == "SPA 49"
    assert view.branch_address == "53/72 ถนนเฉลิมพระเกียรติ ร.9 กรุงเทพฯ 10250"
    assert view.map_url == "https://maps.example/spa49"


def test_admin_projection_does_not_join_detail_without_explicit_render_scope() -> None:
    view = _booking_view(
        FakeClient(), booking_doc_id="booking-1", booking=booking(), admin=True  # type: ignore[arg-type]
    )
    assert isinstance(view, AdminNotificationBookingView)
    assert view.participants[0].has_health_information is True
    assert view.participants[0].health_details is None


def test_admin_projection_does_not_fabricate_phone_for_walk_in() -> None:
    walk_in = {
        **booking(),
        "status": "CONFIRMED",
        "source": "ADMIN_WEB",
        "contact": {"mode": "NONE"},
    }
    view = _booking_view(
        FakeClient(), booking_doc_id="booking-1", booking=walk_in, admin=True  # type: ignore[arg-type]
    )
    assert isinstance(view, AdminNotificationBookingView)
    assert view.contact_phone_display == "ไม่มีเบอร์ติดต่อ"
    assert view.contact_phone_uri is None
    assert view.booking_source == "ADMIN_WEB"
