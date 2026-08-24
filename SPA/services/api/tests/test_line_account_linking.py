import hashlib

from fastapi.testclient import TestClient

from app.api.v1 import bookings
from app.infrastructure.firestore import get_firestore_client
from app.main import app


class Snapshot:
    def __init__(self, document_id: str, data: dict[str, object] | None) -> None:
        self.id = document_id
        self.data = data
        self.exists = data is not None
        self.reference: Document | None = None

    def to_dict(self) -> dict[str, object] | None:
        return self.data


class BookingQuery:
    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot

    def where(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def stream(self):
        return iter([self.snapshot])


class Document:
    def __init__(self, document_id: str, data: dict[str, object] | None = None) -> None:
        self.id = document_id
        self.data = data

    def get(self, transaction=None) -> Snapshot:
        return Snapshot(self.id, self.data)


class Collection:
    def __init__(self, database: "Database", name: str) -> None:
        self.database = database
        self.name = name

    def where(self, *_args, **_kwargs) -> BookingQuery:
        assert self.name == "bookings"
        return BookingQuery(self.database.booking)

    def document(self, document_id: str | None = None) -> Document:
        if self.name == "line_booking_links":
            return self.database.link
        return Document(document_id or "audit-001")


class Transaction:
    def __init__(self, database: "Database") -> None:
        self.database = database

    def set(self, ref: Document, value: dict[str, object], merge: bool = False) -> None:
        if ref is self.database.link:
            self.database.link.data = value
        elif ref is self.database.booking_ref:
            assert self.database.booking.data is not None
            self.database.booking.data.update(value)
        else:
            self.database.audit = value


class Database:
    def __init__(self, status_token: str) -> None:
        self.booking_ref = Document("booking-doc-001")
        self.booking = Snapshot(
            "booking-doc-001",
            {
                "statusTokenHash": hashlib.sha256(status_token.encode()).hexdigest(),
                "status": "CONFIRMED",
            },
        )
        self.booking.reference = self.booking_ref
        self.link = Document("booking-doc-001")
        self.audit: dict[str, object] = {}

    def collection(self, name: str) -> Collection:
        return Collection(self, name)

    def transaction(self) -> Transaction:
        return Transaction(self)


def test_verified_line_identity_is_linked_without_storing_raw_token(monkeypatch) -> None:
    status_token = "status-token-with-at-least-20-characters"
    database = Database(status_token)
    previous = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[get_firestore_client] = lambda: database
    monkeypatch.setattr(bookings.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        bookings,
        "_verify_line_id_token",
        lambda _token: {"sub": "verified-line-user", "aud": "customer-channel"},
    )
    monkeypatch.setattr(
        bookings,
        "get_settings",
        lambda: type("Settings", (), {"line_customer_login_channel_id": "customer-channel"})(),
    )
    try:
        response = TestClient(app).post(
            "/api/v1/public/booking-line-links",
            json={
                "bookingId": "BK-TEST-001",
                "statusToken": status_token,
                "lineIdToken": "raw-line-id-token-must-not-be-stored",
            },
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_firestore_client, None)
        else:
            app.dependency_overrides[get_firestore_client] = previous

    assert response.status_code == 200
    assert response.json() == {
        "bookingId": "BK-TEST-001",
        "linked": True,
        "idempotent": False,
    }
    assert database.link.data is not None
    assert database.link.data["lineUserId"] == "verified-line-user"
    assert "raw-line-id-token" not in str(database.link.data)
    expected_hash = hashlib.sha256(
        b"LINE:customer-channel:verified-line-user"
    ).hexdigest()
    assert database.audit["actorIdHash"] == expected_hash
    assert database.booking.data is not None
    assert database.booking.data["lineIdentityHash"] == expected_hash
    assert database.booking.data["customerListBucket"] == "UPCOMING"


def test_existing_link_backfills_booking_index_without_rewriting_link(monkeypatch) -> None:
    status_token = "status-token-with-at-least-20-characters"
    database = Database(status_token)
    original_link = {
        "bookingDocId": "booking-doc-001",
        "lineUserId": "verified-line-user",
        "channelId": "customer-channel",
        "active": True,
        "version": 3,
    }
    database.link.data = dict(original_link)
    previous = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[get_firestore_client] = lambda: database
    monkeypatch.setattr(bookings.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        bookings,
        "_verify_line_id_token",
        lambda _token: {"sub": "verified-line-user", "aud": "customer-channel"},
    )
    monkeypatch.setattr(
        bookings,
        "get_settings",
        lambda: type("Settings", (), {"line_customer_login_channel_id": "customer-channel"})(),
    )
    try:
        response = TestClient(app).post(
            "/api/v1/public/booking-line-links",
            json={
                "bookingId": "BK-TEST-001",
                "statusToken": status_token,
                "lineIdToken": "raw-line-id-token-must-not-be-stored",
            },
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_firestore_client, None)
        else:
            app.dependency_overrides[get_firestore_client] = previous

    assert response.status_code == 200
    assert response.json()["idempotent"] is True
    assert database.link.data == original_link
    assert database.audit == {}
    assert database.booking.data is not None
    assert "lineIdentityHash" in database.booking.data
