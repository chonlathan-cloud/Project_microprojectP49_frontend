"""
Easy Test Script for Receipts API
==================================
Run:
  cd backend
  source venv/bin/activate
  python tests/test_receipts.py

This mocks ALL external services (Firebase, GCS, Firestore, Document AI)
so you can test the API logic without any cloud credentials or SDKs.
"""
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from io import BytesIO

# =====================================================
# Step 1: Mock ALL Google Cloud / Firebase modules
#         BEFORE any app code is imported.
# =====================================================

# Create mock modules for everything we don't have installed
mock_modules = {
    "firebase_admin": MagicMock(),
    "firebase_admin.auth": MagicMock(),
    "firebase_admin.credentials": MagicMock(),
    "google.cloud": MagicMock(),
    "google.cloud.firestore": MagicMock(),
    "google.cloud.storage": MagicMock(),
    "google.cloud.documentai_v1": MagicMock(),
    "google.cloud.aiplatform": MagicMock(),
    "vertexai": MagicMock(),
    "vertexai.generative_models": MagicMock(),
}

# Inject mocks into sys.modules
for mod_name, mock_mod in mock_modules.items():
    sys.modules[mod_name] = mock_mod

# Make firebase_admin._apps look initialized
sys.modules["firebase_admin"]._apps = {"[DEFAULT]": MagicMock()}

# =====================================================
# Step 2: NOW import app code (with mocked deps)
# =====================================================

from app.main import app
from app.core.security import get_current_user
from fastapi.testclient import TestClient

# =====================================================
# Step 3: Override auth — skip Firebase token checks
# =====================================================

def mock_current_user():
    return {"uid": "test_user_001", "email": "mew@the491.com"}

app.dependency_overrides[get_current_user] = mock_current_user

client = TestClient(app)


# =====================================================
# Test 1: Health Check
# =====================================================

def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    print("✅ Test 1: Health check — PASSED")


# =====================================================
# Test 2: Upload Receipt (Full flow, mocked)
# =====================================================

def test_upload_receipt():
    with patch("app.api.v1.endpoints.receipts.upload_to_gcs") as mock_gcs, \
         patch("app.api.v1.endpoints.receipts.ocr_service") as mock_ocr, \
         patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs, \
         patch("app.api.v1.endpoints.receipts.categorize_line_item") as mock_cat:

        # GCS mock
        mock_gcs.return_value = "gs://the491-receipts/receipts/test.jpg"

        # OCR mock — simulates Document AI response
        mock_ocr.process_invoice.return_value = {
            "text": "Makro\nนมสด Meiji 2L  95.00\nค่าซ่อมแอร์  500.00",
            "entities": [
                {"type": "supplier_name", "mention_text": "Makro", "confidence": 0.95},
                {"type": "line_item", "mention_text": "นมสด Meiji 2L", "confidence": 0.90},
                {"type": "line_item", "mention_text": "ค่าซ่อมแอร์", "confidence": 0.85},
                {"type": "total_amount", "mention_text": "595.00", "confidence": 0.92,
                 "normalized_value": "595.00"},
            ],
            "pages": [{"page_number": 1}],
        }

        # Branch config mock — Coffee shop
        mock_fs.get_branch_config.return_value = {
            "id": "branch_001", "name": "Siam Square One", "type": "COFFEE",
        }

        # Categorization mock
        async def fake_categorize(text, btype):
            if "นม" in text:
                return {"category_id": "C1", "category_name": "COGS", "confidence": 1.0, "source": "RULE"}
            if "ซ่อม" in text:
                return {"category_id": "C5", "category_name": "Equip", "confidence": 1.0, "source": "RULE"}
            return {"category_id": None, "category_name": "Uncategorized", "confidence": 0.0, "source": "NONE"}
        mock_cat.side_effect = fake_categorize

        # Firestore create mock
        mock_fs.create_receipt.return_value = {
            "id": "rcpt_test_123", "status": "DRAFT",
            "items": [
                {"id": "item_1", "description": "Makro", "category_id": None},
                {"id": "item_2", "description": "นมสด Meiji 2L", "category_id": "C1"},
                {"id": "item_3", "description": "ค่าซ่อมแอร์", "category_id": "C5"},
            ],
        }

        # --- Make Request ---
        response = client.post(
            "/api/v1/receipts/upload",
            data={"branch_id": "branch_001"},
            files={"file": ("receipt.jpg", BytesIO(b"fake-image"), "image/jpeg")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test_123"
        assert data["status"] == "DRAFT"
        assert len(data["items"]) == 3

        print("✅ Test 2: Upload receipt — PASSED")
        print(f"   → Receipt ID: {data['receipt_id']}")
        print(f"   → Items categorized: {len(data['items'])}")


# =====================================================
# Test 3: Get Receipt
# =====================================================

def test_get_receipt():
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs:
        mock_fs.get_receipt.return_value = {
            "id": "rcpt_test_123", "branch_id": "branch_001",
            "status": "DRAFT", "items": [],
        }

        response = client.get("/api/v1/receipts/rcpt_test_123")
        assert response.status_code == 200
        assert response.json()["id"] == "rcpt_test_123"
        print("✅ Test 3: Get receipt — PASSED")


# =====================================================
# Test 4: Get Receipt — Not Found (404)
# =====================================================

def test_get_receipt_not_found():
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs:
        mock_fs.get_receipt.return_value = None

        response = client.get("/api/v1/receipts/nonexistent")
        assert response.status_code == 404
        print("✅ Test 4: Get receipt 404 — PASSED")


# =====================================================
# Test 5: Verify Receipt
# =====================================================

def test_verify_receipt():
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs:
        mock_fs.get_receipt.return_value = {"id": "rcpt_test_123", "status": "DRAFT"}
        mock_fs.update_receipt_status.return_value = {"id": "rcpt_test_123", "status": "VERIFIED"}

        response = client.put(
            "/api/v1/receipts/rcpt_test_123/verify",
            json={
                "items": [
                    {"description": "นมสด", "amount": 95.0, "category_id": "C1"},
                    {"description": "ค่าซ่อมแอร์", "amount": 500.0, "category_id": "C5"},
                ],
                "total_check": 595.0,
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "VERIFIED"
        print("✅ Test 5: Verify receipt — PASSED")


# =====================================================
# Test 6: Verify Receipt — Bad Total (400)
# =====================================================

def test_verify_bad_total():
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs:
        mock_fs.get_receipt.return_value = {"id": "rcpt_test_123", "status": "DRAFT"}

        response = client.put(
            "/api/v1/receipts/rcpt_test_123/verify",
            json={
                "items": [
                    {"description": "นมสด", "amount": 95.0, "category_id": "C1"},
                ],
                "total_check": 999.0,  # Wrong!
            },
        )

        assert response.status_code == 400
        print("✅ Test 6: Verify bad total 400 — PASSED")


# =====================================================
# Run all
# =====================================================

if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  Receipts API Tests (all services mocked)")
    print("=" * 50)
    print()

    test_health_check()
    test_upload_receipt()
    test_get_receipt()
    test_get_receipt_not_found()
    test_verify_receipt()
    test_verify_bad_total()

    print()
    print("=" * 50)
    print("  🎉 All 6 tests passed!")
    print("=" * 50)
    print()
