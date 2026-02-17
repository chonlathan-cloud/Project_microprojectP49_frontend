import uuid
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from google.cloud import storage

from app.core.config import settings
from app.core.security import get_current_user
from app.services import ocr_service, firestore_service, bigquery_service
from app.services.categorization import categorize_line_item
from app.models.receipt import ReceiptVerify

# Reference: LDD Section 4, TDD Section 2.1

router = APIRouter(prefix="/receipts", tags=["Receipts"])

# --- GCS Upload Helper ---

gcs_client = storage.Client(project=settings.GCP_PROJECT_ID)
bucket = gcs_client.bucket(settings.GCP_STORAGE_BUCKET)


async def upload_to_gcs(file: UploadFile) -> str:
    """
    Upload a file to Google Cloud Storage.

    Args:
        file: The uploaded file from the request.

    Returns:
        str: The public GCS URI (gs://bucket/path).
    """
    file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
    blob_name = f"receipts/{uuid.uuid4()}.{file_ext}"
    blob = bucket.blob(blob_name)

    content = await file.read()
    blob.upload_from_string(content, content_type=file.content_type)

    return f"gs://{settings.GCP_STORAGE_BUCKET}/{blob_name}"


# =====================================================
# 1. POST /upload — Upload & Process Receipt
# Reference: TDD Section 2.1 (Upload Receipt)
# =====================================================

@router.post("/upload")
async def upload_receipt(
    branch_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload a receipt image → GCS → OCR → Auto-Categorize → Save as DRAFT.

    Flow (LDD Section 4):
    1. Upload file to GCS
    2. Process OCR via Document AI
    3. Get branch config (business type)
    4. Auto-categorize each line item
    5. Save draft to Firestore
    """
    try:
        # 1. Upload to GCS
        file_content = await file.read()
        await file.seek(0)  # Reset for GCS upload
        gcs_uri = await upload_to_gcs(file)

        # 2. Process OCR
        ocr_data = ocr_service.process_invoice(file_content, file.content_type)

        # 3. Get Branch Info (to know if Coffee or Restaurant)
        branch_info = firestore_service.get_branch_config(branch_id)
        if not branch_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Branch '{branch_id}' not found.",
            )

        business_type = branch_info.get("type", "COFFEE")

        # 4. Auto-Categorize Items
        enriched_items = []
        for idx, entity in enumerate(ocr_data.get("entities", [])):
            description = entity.get("mention_text", "")
            if not description:
                continue

            cat_result = await categorize_line_item(description, business_type)

            enriched_items.append({
                "id": f"item_{idx + 1}",
                "description": description,
                "amount": 0.0,  # Amount extracted separately from OCR
                "category_id": cat_result.get("category_id"),
                "category_name": cat_result.get("category_name"),
                "confidence": cat_result.get("confidence", 0.0),
                "is_manual_edit": False,
            })

        # 5. Save Draft to Firestore
        receipt_doc = {
            "branch_id": branch_id,
            "user_id": current_user["uid"],
            "status": "DRAFT",
            "image_url": gcs_uri,
            "header": {
                "merchant": None,
                "date": None,
                "total": 0.0,
            },
            "items": enriched_items,
        }

        # Extract header info from OCR entities
        for entity in ocr_data.get("entities", []):
            etype = entity.get("type", "").lower()
            if "date" in etype:
                receipt_doc["header"]["date"] = entity.get("mention_text")
            elif "total" in etype or "amount" in etype:
                try:
                    receipt_doc["header"]["total"] = float(
                        entity.get("normalized_value", entity.get("mention_text", "0"))
                    )
                except (ValueError, TypeError):
                    pass
            elif "supplier" in etype or "vendor" in etype or "merchant" in etype:
                receipt_doc["header"]["merchant"] = entity.get("mention_text")

        saved_receipt = firestore_service.create_receipt(receipt_doc)

        return {
            "receipt_id": saved_receipt["id"],
            "status": saved_receipt["status"],
            "items": saved_receipt["items"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process receipt: {str(e)}",
        )


# =====================================================
# 2. GET /{receipt_id} — Get Receipt Detail
# Reference: TDD Section 2.1 (Get Receipt Detail)
# =====================================================

@router.get("/{receipt_id}")
async def get_receipt(
    receipt_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve receipt details for the Side-by-Side validation view.
    """
    receipt = firestore_service.get_receipt(receipt_id)

    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receipt '{receipt_id}' not found.",
        )

    return receipt


# =====================================================
# 3. PUT /{receipt_id}/verify — Verify & Submit
# Reference: TDD Section 2.1 (Verify & Submit)
# =====================================================

@router.put("/{receipt_id}/verify")
async def verify_receipt(
    receipt_id: str,
    verified_data: ReceiptVerify,
    current_user: dict = Depends(get_current_user),
):
    """
    User confirms the receipt data → Update Firestore to VERIFIED.

    The frontend sends corrected items with total_check.
    Total must match sum of item amounts.
    """
    # Check receipt exists
    existing = firestore_service.get_receipt(receipt_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receipt '{receipt_id}' not found.",
        )

    # Validate total_check matches sum of items
    items_total = sum(item.amount for item in verified_data.items)
    if abs(items_total - verified_data.total_check) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Total check ({verified_data.total_check}) does not match "
                   f"sum of items ({items_total}).",
        )

    # Convert Pydantic models to dicts for Firestore
    update_payload = {
        "items": [item.model_dump() for item in verified_data.items],
        "total_check": verified_data.total_check,
        "verified_by": current_user["uid"],
    }

    updated = firestore_service.update_receipt_status(
        receipt_id=receipt_id,
        status="VERIFIED",
        verified_data=update_payload,
    )

    # Insert verified data into BigQuery (fact_transactions)
    # Reference: TDD Section 1.2, HLD Flow A Step 6
    try:
        rows_inserted = bigquery_service.insert_verified_receipt(updated)
    except Exception:
        # Log but don't fail — Firestore is already updated
        rows_inserted = 0

    return {
        "receipt_id": receipt_id,
        "status": "VERIFIED",
        "message": "Receipt verified and saved successfully.",
        "bigquery_rows_inserted": rows_inserted,
    }
