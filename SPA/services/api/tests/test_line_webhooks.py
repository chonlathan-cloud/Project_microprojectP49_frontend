import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists

from app.api.v1 import webhooks
from app.infrastructure.firestore import get_firestore_client
from app.integrations.line_identity import line_identity_hash
from app.main import app


class FakeDocument:
    def __init__(self, store: dict[str, dict[str, object]], key: str) -> None:
        self.store = store
        self.key = key
        self.id = key

    def create(self, value: dict[str, object]) -> None:
        if self.key in self.store:
            raise AlreadyExists("duplicate")
        self.store[self.key] = value

    def get(self, transaction=None):
        value = self.store.get(self.key)
        return type(
            "Snapshot",
            (),
            {
                "exists": value is not None,
                "to_dict": lambda _self: dict(value) if value is not None else None,
            },
        )()

    def set(self, value: dict[str, object], merge: bool = False) -> None:
        if merge and self.key in self.store:
            self.store[self.key].update(value)
        else:
            self.store[self.key] = value


class FakeCollection:
    def __init__(self, database: "FakeFirestore", store: dict[str, dict[str, object]]) -> None:
        self.database = database
        self.store = store

    def document(self, key: str | None = None) -> FakeDocument:
        if key is None:
            self.database.counter += 1
            key = f"generated-{self.database.counter:03d}"
        return FakeDocument(self.store, key)


class FakeTransaction:
    def set(self, ref: FakeDocument, value: dict[str, object], merge: bool = False) -> None:
        ref.set(value, merge=merge)


class FakeFirestore:
    def __init__(self) -> None:
        self.counter = 0
        self.events: dict[str, dict[str, object]] = {}
        self.groups: dict[str, dict[str, object]] = {}
        self.identities: dict[str, dict[str, object]] = {}
        self.friendships: dict[str, dict[str, object]] = {}
        self.customers: dict[str, dict[str, object]] = {}

    def collection(self, name: str) -> FakeCollection:
        stores = {
            "line_webhook_events": self.events,
            "line_group_candidates": self.groups,
            "customer_identity_links": self.identities,
            "line_friendships": self.friendships,
            "customers": self.customers,
        }
        return FakeCollection(self, stores[name])

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()


fake_firestore = FakeFirestore()
client = TestClient(app)


def signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@pytest.fixture(autouse=True)
def use_fake_firestore():
    previous = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[get_firestore_client] = lambda: fake_firestore
    yield
    if previous is None:
        app.dependency_overrides.pop(get_firestore_client, None)
    else:
        app.dependency_overrides[get_firestore_client] = previous


def test_customer_webhook_accepts_empty_verification(monkeypatch) -> None:
    monkeypatch.setenv("LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET", "customer-secret")
    body = b'{"destination":"test","events":[]}'
    response = client.post(
        "/api/v1/webhooks/line/customer",
        content=body,
        headers={"x-line-signature": signature(body, "customer-secret")},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "accepted": 0, "duplicates": 0}


def test_admin_webhook_rejects_wrong_channel_secret(monkeypatch) -> None:
    monkeypatch.setenv("LINE_ADMIN_MESSAGING_CHANNEL_SECRET", "admin-secret")
    body = b'{"destination":"test","events":[]}'
    response = client.post(
        "/api/v1/webhooks/line/admin",
        content=body,
        headers={"x-line-signature": signature(body, "customer-secret")},
    )
    assert response.status_code == 401


def test_webhook_event_is_deduplicated(monkeypatch) -> None:
    monkeypatch.setenv("LINE_ADMIN_MESSAGING_CHANNEL_SECRET", "admin-secret")
    fake_firestore.events.clear()
    fake_firestore.groups.clear()
    body = json.dumps(
        {
            "destination": "test",
            "events": [
                {
                    "webhookEventId": "evt-001",
                    "type": "message",
                    "timestamp": 1,
                    "source": {"type": "group", "groupId": "group", "userId": "user"},
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    headers = {"x-line-signature": signature(body, "admin-secret")}
    first = client.post("/api/v1/webhooks/line/admin", content=body, headers=headers)
    second = client.post("/api/v1/webhooks/line/admin", content=body, headers=headers)
    assert first.json()["accepted"] == 1
    assert second.json()["duplicates"] == 1
    stored = next(iter(fake_firestore.events.values()))
    assert "groupId" not in stored
    assert "userId" not in stored
    candidate = next(iter(fake_firestore.groups.values()))
    assert candidate["groupId"] == "group"
    assert candidate["channel"] == "admin"
    assert "userId" not in candidate


def test_customer_webhook_does_not_capture_group_candidate(monkeypatch) -> None:
    monkeypatch.setenv("LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET", "customer-secret")
    fake_firestore.groups.clear()
    body = json.dumps(
        {
            "events": [
                {
                    "webhookEventId": "evt-customer-group",
                    "type": "message",
                    "source": {"type": "group", "groupId": "customer-group"},
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    response = client.post(
        "/api/v1/webhooks/line/customer",
        content=body,
        headers={"x-line-signature": signature(body, "customer-secret")},
    )
    assert response.status_code == 200
    assert fake_firestore.groups == {}


def test_customer_follow_records_friendship_without_creating_crm_customer(monkeypatch) -> None:
    monkeypatch.setenv("LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET", "customer-secret")
    monkeypatch.setattr(webhooks.firestore, "transactional", lambda function: function)
    fake_firestore.events.clear()
    fake_firestore.identities.clear()
    fake_firestore.friendships.clear()
    fake_firestore.customers.clear()
    body = json.dumps(
        {
            "events": [
                {
                    "webhookEventId": "evt-follow-001",
                    "type": "follow",
                    "timestamp": 1787216400000,
                    "source": {"type": "user", "userId": "line-user-001"},
                }
            ]
        },
        separators=(",", ":"),
    ).encode()

    response = client.post(
        "/api/v1/webhooks/line/customer",
        content=body,
        headers={"x-line-signature": signature(body, "customer-secret")},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    friendship = next(iter(fake_firestore.friendships.values()))
    assert fake_firestore.identities == {}
    assert fake_firestore.customers == {}
    assert friendship["status"] == "FOLLOWING"
    assert friendship["evidenceSource"] == "WEBHOOK"
    assert "lineUserId" not in friendship


def test_customer_follow_updates_existing_crm_customer(monkeypatch) -> None:
    monkeypatch.setenv("LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET", "customer-secret")
    monkeypatch.setattr(webhooks.firestore, "transactional", lambda function: function)
    fake_firestore.events.clear()
    fake_firestore.friendships.clear()
    fake_firestore.customers.clear()
    fake_firestore.identities.clear()
    identity_id = line_identity_hash("line-user-002")
    fake_firestore.identities[identity_id] = {
        "customerId": "customer-002",
        "friendStatus": "UNKNOWN",
    }
    fake_firestore.customers["customer-002"] = {"source": "LINE_CAMPAIGN"}
    body = json.dumps(
        {
            "events": [
                {
                    "webhookEventId": "evt-follow-002",
                    "type": "follow",
                    "timestamp": 1787216400000,
                    "source": {"type": "user", "userId": "line-user-002"},
                }
            ]
        },
        separators=(",", ":"),
    ).encode()

    response = client.post(
        "/api/v1/webhooks/line/customer",
        content=body,
        headers={"x-line-signature": signature(body, "customer-secret")},
    )

    assert response.status_code == 200
    assert fake_firestore.identities[identity_id]["friendStatus"] == "FOLLOWING"
    assert fake_firestore.customers["customer-002"]["friendStatus"] == "FOLLOWING"
