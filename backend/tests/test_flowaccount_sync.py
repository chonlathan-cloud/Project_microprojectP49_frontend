"""
Mocked tests for receipt verification with FlowAccount sync.

Run:
  cd backend
  PYTHONPATH=. python tests/test_flowaccount_sync.py
"""
import sys
from unittest.mock import MagicMock, patch


mock_modules = {
    "firebase_admin": MagicMock(),
    "firebase_admin.auth": MagicMock(),
    "firebase_admin.credentials": MagicMock(),
    "google.cloud": MagicMock(),
    "google.cloud.firestore": MagicMock(),
    "google.cloud.storage": MagicMock(),
    "google.cloud.bigquery": MagicMock(),
    "google.cloud.documentai_v1": MagicMock(),
    "google.cloud.aiplatform": MagicMock(),
    "vertexai": MagicMock(),
    "vertexai.generative_models": MagicMock(),
}

for mod_name, mock_mod in mock_modules.items():
    sys.modules[mod_name] = mock_mod

sys.modules["firebase_admin"]._apps = {"[DEFAULT]": MagicMock()}

from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.services import flowaccount_service as real_flowaccount_service


def mock_current_user():
    return {"uid": "admin_user_001", "email": "admin@the49.com"}


app.dependency_overrides[get_current_user] = mock_current_user
client = TestClient(app)


def _verified_receipt(flowaccount_synced=False):
    return {
        "id": "receipt_123",
        "branch_id": "branch_001",
        "status": "VERIFIED",
        "bigquery_synced": True,
        "flowaccount_synced": flowaccount_synced,
        "image_url": "gs://the491-receipts/receipts/test.jpg",
        "header": {"merchant": "Makro", "date": "2026-06-29", "total": 95.0},
        "items": [
            {
                "description": "Milk",
                "amount": 95.0,
                "category_id": "C1",
                "category_name": "COGS",
            }
        ],
        "adjustments": [],
        "total_check": 95.0,
    }


def test_paid_expense_payload_uses_seller_contact_fields():
    receipt = {
        "id": "receipt_123",
        "header": {
            "merchant": "Fallback Merchant",
            "date": "2026-06-29",
            "total": 9630.0,
        },
        "items": [
            {
                "description": "ค่าออกแบบลายเสื้อ",
                "amount": 5000.0,
                "category_name": "Admin",
            },
            {
                "description": "ค่าพิมพ์เสื้อ",
                "amount": 4000.0,
                "category_name": "Admin",
            },
        ],
        "adjustments": [],
        "total_check": 9000.0,
        "OCRbyGemini": {
            "seller": {
                "legal_name": "บริษัท ซันเดย์ มาร์เก็ตติ้ง จำกัด",
                "branch_name": "สำนักงานใหญ่",
                "tax_id": "0123456789123",
                "contact_person": "คุณสมชาย",
                "email": "contact@sundaymarketing.co.th",
                "phone": "061-234-0000",
                "address": "88/8 หมู่ที่ 3 ตำบลบางแม่นาง อำเภอบางใหญ่ จังหวัดนนทบุรี 11140",
            }
        },
    }

    with patch("app.services.flowaccount_service.ensure_expense_configured"):
        payload = real_flowaccount_service.build_paid_expense_payload(
            receipt=receipt,
            branch={"id": "branch_001", "name": "Siam Square One"},
            payment_method="CASH",
        )

    assert payload["contactName"] == "บริษัท ซันเดย์ มาร์เก็ตติ้ง จำกัด"
    assert payload["contactGroup"] == 3
    assert payload["contactBranch"] == "สำนักงานใหญ่"
    assert payload["contactTaxId"] == "0123456789123"
    assert payload["contactPerson"] == "คุณสมชาย"
    assert payload["contactEmail"] == "contact@sundaymarketing.co.th"
    assert payload["contactNumber"] == "061-234-0000"
    assert "นนทบุรี" in payload["contactAddress"]
    print("FlowAccount seller contact payload - PASSED")


def test_verify_save_and_sync_success():
    updated_receipt = _verified_receipt()
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs, \
         patch("app.api.v1.endpoints.receipts.bigquery_service") as mock_bq, \
         patch("app.api.v1.endpoints.receipts.flowaccount_service") as mock_flow:

        mock_fs.get_user_profile.return_value = {"role": "admin"}
        mock_fs.get_receipt.return_value = {
            "id": "receipt_123",
            "branch_id": "branch_001",
            "status": "DRAFT",
            "image_url": "gs://the491-receipts/receipts/test.jpg",
            "header": {"merchant": "Makro", "date": "2026-06-29", "total": 95.0},
        }
        mock_fs.get_branch_config.return_value = {
            "id": "branch_001",
            "name": "Siam Square One",
            "type": "COFFEE",
        }
        mock_fs.update_receipt_status.return_value = updated_receipt
        mock_fs.update_receipt_fields.return_value = updated_receipt
        mock_fs.record_receipt_flowaccount_sync.return_value = {
            **updated_receipt,
            "flowaccount_synced": True,
        }
        mock_bq.insert_verified_receipt.return_value = 1
        mock_flow.ensure_configured.return_value = None
        mock_flow.create_paid_expense_from_receipt.return_value = {
            "recordId": 123,
            "documentId": 456,
            "documentSerial": "EXP2026060001",
        }
        mock_flow.attach_receipt_file.return_value = {"status": True}

        response = client.post(
            "/api/v1/receipts/receipt_123/verify-and-sync-flowaccount",
            json={
                "items": [
                    {"description": "Milk", "amount": 95.0, "category_id": "C1"}
                ],
                "adjustments": [],
                "total_check": 95.0,
                "confirm_resync": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["flowaccount_synced"] is True
        assert data["flowaccount_record_id"] == "123"
        assert data["flowaccount_document_serial"] == "EXP2026060001"
        mock_flow.create_paid_expense_from_receipt.assert_called_once()
        mock_flow.attach_receipt_file.assert_called_once()
        print("✅ Verify/save/sync success — PASSED")


def test_already_synced_requires_confirmation():
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs, \
         patch("app.api.v1.endpoints.receipts.flowaccount_service") as mock_flow:

        mock_fs.get_user_profile.return_value = {"role": "admin"}
        mock_fs.get_receipt.return_value = _verified_receipt(flowaccount_synced=True)
        mock_flow.ensure_configured.return_value = None

        response = client.post(
            "/api/v1/receipts/receipt_123/verify-and-sync-flowaccount",
            json={
                "items": [
                    {"description": "Milk", "amount": 95.0, "category_id": "C1"}
                ],
                "adjustments": [],
                "total_check": 95.0,
                "confirm_resync": False,
            },
        )

        assert response.status_code == 409
        mock_flow.create_paid_expense_from_receipt.assert_not_called()
        print("✅ Already-synced confirmation block — PASSED")


def test_staff_role_is_blocked():
    with patch("app.api.v1.endpoints.receipts.firestore_service") as mock_fs, \
         patch("app.api.v1.endpoints.receipts.flowaccount_service") as mock_flow:

        mock_fs.get_user_profile.return_value = {"role": "staff"}

        response = client.post(
            "/api/v1/receipts/receipt_123/verify-and-sync-flowaccount",
            json={
                "items": [
                    {"description": "Milk", "amount": 95.0, "category_id": "C1"}
                ],
                "adjustments": [],
                "total_check": 95.0,
                "confirm_resync": False,
            },
        )

        assert response.status_code == 403
        mock_flow.ensure_configured.assert_not_called()
        print("✅ Staff role block — PASSED")


if __name__ == "__main__":
    print()
    print("=" * 56)
    print("  FlowAccount Sync Tests (all external services mocked)")
    print("=" * 56)
    print()

    test_paid_expense_payload_uses_seller_contact_fields()
    test_verify_save_and_sync_success()
    test_already_synced_requires_confirmation()
    test_staff_role_is_blocked()

    print()
    print("=" * 56)
    print("  All FlowAccount sync tests passed.")
    print("=" * 56)
