from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_public_catalog_is_available() -> None:
    response = client.get("/api/v1/public/services")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 11
    serialized = str(payload)
    assert "resourceRequirements" not in serialized
    assert "allocationPriority" not in serialized


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
