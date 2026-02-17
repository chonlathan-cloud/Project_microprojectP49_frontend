"""
Real Scenario Test for Receipts API
====================================
Run:
  (First, ensure your backend/.env file is configured)
  cd backend
  source venv/bin/activate
  TEST_BRANCH_ID=branch_001 PYTHONPATH=. python tests/test_real_scenario.py
"""
import os
from fastapi.testclient import TestClient

# Important: We are NOT mocking any cloud services here.
# This relies on a valid .env file being present.

from app.main import app
from app.core.security import get_current_user

# =====================================================
# Override auth — skip Firebase token checks
# We are still mocking auth to avoid needing a live user token.
# =====================================================

def mock_current_user():
    return {"uid": "test_user_real_scenario", "email": "real_test@the491.com"}

app.dependency_overrides[get_current_user] = mock_current_user

client = TestClient(app)

# =====================================================
# Test 1: Upload Real Receipt and Fetch Draft
# =====================================================

def test_upload_and_process_real_receipt():
    """
    Tests the full, real flow:
    1. Uploads the test image.
    2. Fetches the saved receipt detail.
    3. Checks status/data in DRAFT state.
    """
    print("🚀 Starting real scenario test...")
    branch_id = os.getenv("TEST_BRANCH_ID", "branch_001")
    print(f"   -> Using branch_id='{branch_id}'")

    # --- 1. Upload the receipt ---
    image_path = "backend/bill for test2.jpg" # Assumes file is in 'backend' dir
    if not os.path.exists(image_path):
        print(f"🔴 ERROR: Test image not found at '{image_path}'")
        print("   Please ensure 'bill for test.jpg' is in the 'backend' directory.")
        assert False, "Test image not found"

    print(f"   -> Uploading '{image_path}'...")
    with open(image_path, "rb") as f:
        response = client.post(
            "/api/v1/receipts/upload",
            data={"branch_id": branch_id},
            files={"file": (os.path.basename(image_path), f, "image/jpeg")},
        )

    if response.status_code != 200:
        print("   🔴 FAILED: Initial upload failed.")
        print(f"   Response: {response.json()}")
    assert response.status_code == 200, "Initial upload request failed"

    data = response.json()
    receipt_id = data.get("receipt_id")
    assert receipt_id is not None, "API did not return a receipt_id"

    print(f"   ✅ Upload successful. Receipt ID: {receipt_id}")
    print("   -> Fetching receipt detail...")

    # --- 2. Fetch saved receipt ---
    response = client.get(f"/api/v1/receipts/{receipt_id}")
    if response.status_code != 200:
        print("   🔴 FAILED: Fetch receipt failed.")
        print(f"   Response: {response.json()}")
    assert response.status_code == 200, "Get receipt request failed"

    # --- 3. Check final result ---
    final_receipt = response.json()
    status = final_receipt.get("status")
    print(f"   ✅ Current status: '{status}'")

    assert final_receipt["id"] == receipt_id
    assert status == "DRAFT", f"Expected DRAFT status right after upload, got '{status}'"
    assert len(final_receipt["items"]) > 0, "Upload succeeded, but no items were extracted."

    print("   -> Final extracted items:")
    for item in final_receipt["items"]:
        print(f"      - {item['description']}: {item['amount']} (Category: {item.get('category_id', 'N/A')})")

    print("\n✅ Test 'test_upload_and_process_real_receipt' — PASSED")

if __name__ == "__main__":
    test_upload_and_process_real_receipt()
