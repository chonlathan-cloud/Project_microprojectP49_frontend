from google.cloud import firestore
from datetime import datetime
from typing import Optional

from app.core.config import settings

# --- Firestore Client ---
# Reference: TDD Section 1.1, LDD Section 3

db = firestore.Client(
    project=settings.GCP_PROJECT_ID,
    database=settings.FIRESTORE_DB,
)


# =====================================================
# Receipt Operations
# Collection: "receipts" (TDD Section 1.1)
# =====================================================

def create_receipt(data: dict) -> dict:
    """
    Create a new receipt document in Firestore.

    Args:
        data: Dict containing receipt fields (branch_id, user_id,
              status, image_url, header, items, etc.)

    Returns:
        dict: The saved document data including the generated 'id'.
    """
    # Let Firestore auto-generate the document ID
    doc_ref = db.collection("receipts").document()
    data["id"] = doc_ref.id
    data["created_at"] = datetime.utcnow().isoformat()
    data["status"] = data.get("status", "DRAFT")
    data["verified_at"] = None
    data["verified_by"] = None
    data["bigquery_synced"] = False
    data["bigquery_rows_inserted"] = 0

    doc_ref.set(data)
    return data


def get_receipt(receipt_id: str) -> Optional[dict]:
    """
    Retrieve a single receipt document by ID.

    Args:
        receipt_id: The Firestore document ID.

    Returns:
        dict or None: The receipt data, or None if not found.
    """
    doc = db.collection("receipts").document(receipt_id).get()
    if doc.exists:
        return doc.to_dict()
    return None


def list_receipts(
    status: str | None = None,
    branch_id: str | None = None,
    user_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    List receipt documents with optional filters.
    """
    query = db.collection("receipts")

    if status:
        query = query.where("status", "==", status)
    if branch_id:
        query = query.where("branch_id", "==", branch_id)
    if user_id:
        query = query.where("user_id", "==", user_id)

    docs = query.limit(max(1, min(limit, 200))).stream()
    receipts: list[dict] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "id" not in data:
            data["id"] = doc.id
        receipts.append(data)

    receipts.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return receipts


def update_receipt_status(
    receipt_id: str,
    status: str,
    verified_data: dict,
) -> dict:
    """
    Update a receipt's status (e.g., DRAFT -> VERIFIED) and
    optionally overwrite items with user-verified data.

    Reference: TDD Section 2.1 (PUT /receipts/{id}/verify)

    Args:
        receipt_id: The Firestore document ID.
        status: New status string ("VERIFIED" or "REJECTED").
        verified_data: Dict with corrected 'items' and 'total_check'.

    Returns:
        dict: The updated document data.
    """
    doc_ref = db.collection("receipts").document(receipt_id)

    update_payload = {
        "status": status,
        "verified_at": datetime.utcnow().isoformat(),
    }

    # Merge user-corrected items if provided
    if "items" in verified_data:
        update_payload["items"] = verified_data["items"]
    if "total_check" in verified_data:
        update_payload["total_amount"] = verified_data["total_check"]
    if "verified_by" in verified_data:
        update_payload["verified_by"] = verified_data["verified_by"]

    doc_ref.update(update_payload)

    # Return the full updated document
    return doc_ref.get().to_dict()


def update_receipt_fields(receipt_id: str, fields: dict) -> dict:
    """
    Update arbitrary receipt fields and return the updated document.
    """
    doc_ref = db.collection("receipts").document(receipt_id)
    doc_ref.update(fields)
    return doc_ref.get().to_dict()


# =====================================================
# Branch Operations
# Collection: "branches" (TDD Section 1.1)
# =====================================================

def get_branch_config(branch_id: str) -> Optional[dict]:
    """
    Retrieve branch configuration (name, type) from Firestore.
    The 'type' field determines which expense categories to use
    (COFFEE -> C1-C9, RESTAURANT -> F1-F7).

    Reference: TDD Section 1.1, BusinessLogic Section 1

    Args:
        branch_id: The branch document ID (e.g., "branch_001").

    Returns:
        dict or None: Branch data including 'type', or None if not found.
    """
    doc = db.collection("branches").document(branch_id).get()
    if doc.exists:
        return doc.to_dict()
    return None


def list_branches() -> list[dict]:
    """
    List all branch documents from Firestore.

    Returns:
        list[dict]: Each branch contains at least id, name, type.
    """
    docs = db.collection("branches").stream()
    branches: list[dict] = []

    for doc in docs:
        data = doc.to_dict() or {}
        branch = {
            "id": data.get("id", doc.id),
            "name": data.get("name", ""),
            "type": data.get("type", "RESTAURANT"),
        }
        branches.append(branch)

    branches.sort(key=lambda item: item.get("name", ""))
    return branches
