from fastapi.testclient import TestClient

from app.main import app


def test_readiness_is_fail_closed_by_default() -> None:
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["reasonCodes"] == ["SYNC_DISABLED"]
