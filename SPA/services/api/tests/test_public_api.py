from fastapi.testclient import TestClient

from app.infrastructure.firestore import get_firestore_client
from app.main import app


class MissingSnapshot:
    exists = False

    def to_dict(self):
        return None


class EmptyCollection:
    def document(self, *_):
        return self

    def get(self):
        return MissingSnapshot()

    def where(self, *_args, **_kwargs):
        return self

    def limit(self, *_):
        return self

    def stream(self):
        return iter(())


class EmptyFirestore:
    def collection(self, *_):
        return EmptyCollection()


class ExistingServiceSnapshot:
    id = "complete-relaxation"

    def to_dict(self):
        return {
            "serviceId": self.id,
            "category": "SIGNATURE",
            "nameTh": "แพ็กเกจผ่อนคลายครบสูตร",
            "nameEn": "Complete Relaxation Ritual",
            "descriptionTh": "คำอธิบายที่แก้จาก Admin",
            "active": True,
            "variants": [],
        }


class ExistingServiceCollection(EmptyCollection):
    def stream(self):
        return iter((ExistingServiceSnapshot(),))


class ExistingServiceFirestore:
    def collection(self, *_):
        return ExistingServiceCollection()


app.dependency_overrides[get_firestore_client] = EmptyFirestore

client = TestClient(app)


def test_public_catalog_is_available() -> None:
    response = client.get("/api/v1/public/services")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 11
    assert all(item["descriptionTh"] for item in payload["items"])
    assert all(item["descriptionEn"] for item in payload["items"])
    serialized = str(payload)
    assert "resourceRequirements" not in serialized
    assert "allocationPriority" not in serialized


def test_firestore_copy_wins_and_missing_language_uses_seed_during_migration() -> None:
    app.dependency_overrides[get_firestore_client] = ExistingServiceFirestore
    try:
        response = client.get("/api/v1/public/services")
    finally:
        app.dependency_overrides[get_firestore_client] = EmptyFirestore

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["descriptionTh"] == "คำอธิบายที่แก้จาก Admin"
    assert item["descriptionEn"].startswith("A complete relaxation ritual")


def test_availability_does_not_invent_capacity_before_configuration() -> None:
    response = client.post(
        "/api/v1/public/availability/search",
        json={
            "branchId": "branch_001",
            "dateFrom": "2026-08-15",
            "dateTo": "2026-08-15",
            "participants": [{"serviceVariantId": "aroma-therapy-60"}],
        },
    )
    assert response.status_code == 200
    assert response.json()["slots"] == []
    assert response.json()["configurationState"] == "RESOURCE_CONFIGURATION_REQUIRED"
