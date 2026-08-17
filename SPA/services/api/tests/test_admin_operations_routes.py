from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.auth import require_admin_user
from app.infrastructure.firestore import get_firestore_client
from app.main import app

client = TestClient(app)


def test_admin_phase_one_modules_require_authentication() -> None:
    for path in (
        "/api/v1/admin/resources",
        "/api/v1/admin/closures",
        "/api/v1/admin/services",
        "/api/v1/admin/therapists",
        "/api/v1/admin/notifications",
        "/api/v1/admin/line-group-candidates",
    ):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["detail"] == "Bearer token required"


class FakeSnapshot:
    exists = True

    def to_dict(self) -> dict[str, object]:
        return {"state": "ENQUEUED", "enqueueGeneration": 0}


class FakeDocument:
    def __init__(self) -> None:
        self.update: dict[str, object] = {}

    def get(self) -> FakeSnapshot:
        return FakeSnapshot()

    def set(self, value: dict[str, object], merge: bool = False) -> None:
        assert merge is True
        self.update = value


class FakeCollection:
    def __init__(self, notification: FakeDocument) -> None:
        self.notification = notification

    def document(self, document_id: str | None = None):
        if document_id == "event-001":
            return self.notification
        return type("AuditDocument", (), {"set": lambda self, value: None})()


class FakeFirestore:
    def __init__(self) -> None:
        self.notification = FakeDocument()

    def collection(self, name: str) -> FakeCollection:
        assert name in {"notification_outbox", "audit_events"}
        return FakeCollection(self.notification)


def test_notification_retry_advances_enqueue_generation() -> None:
    database = FakeFirestore()
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {"uid": "admin-001"}
    app.dependency_overrides[get_firestore_client] = lambda: database
    try:
        response = client.post("/api/v1/admin/notifications/event-001:retry")
    finally:
        if previous_auth is None:
            app.dependency_overrides.pop(require_admin_user, None)
        else:
            app.dependency_overrides[require_admin_user] = previous_auth
        if previous_firestore is None:
            app.dependency_overrides.pop(get_firestore_client, None)
        else:
            app.dependency_overrides[get_firestore_client] = previous_firestore

    assert response.status_code == 200
    assert response.json() == {"eventId": "event-001", "state": "RETRYABLE"}
    assert database.notification.update["state"] == "RETRYABLE"
    increment = database.notification.update["enqueueGeneration"]
    assert isinstance(increment, firestore.Increment)
    assert increment.value == 1
