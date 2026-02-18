import uuid
import logging
import re
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query, status
from google.cloud import storage

from app.core.config import settings
from app.core.security import get_current_user
from app.models.branch import get_categories_for_type
from app.models.receipt import BusinessType, ReceiptVerify
from app.services import ai_service, bigquery_service, firestore_service, ocr_service
from app.services.categorization import categorize_line_item, categorize_line_item_rule_only

# Reference: LDD Section 4, TDD Section 2.1

router = APIRouter(prefix="/receipts", tags=["Receipts"])
logger = logging.getLogger(__name__)

# --- GCS Upload Helper ---

gcs_client = storage.Client(project=settings.GCP_PROJECT_ID)
bucket = gcs_client.bucket(settings.GCP_STORAGE_BUCKET)
FALLBACK_NOISE_KEYWORDS = (
    "tax id",
    "tax invoice",
    "receipt",
    "vat",
    "online card",
    "onlinecard",
    "promptpay",
    "promptp",
    "member",
    "qr",
    "โทร",
    "คะแนน",
)
DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)


def _normalize_extraction_mode(raw_mode: str | None) -> str:
    mode = (raw_mode or "").strip().lower()
    if mode not in {"vision_first", "ocr_first"}:
        return "vision_first"
    return mode


def _normalize_receipt_status(raw_status: str | None) -> str | None:
    if not raw_status:
        return None
    normalized = raw_status.strip().upper()
    if normalized not in {"DRAFT", "VERIFIED", "REJECTED"}:
        return None
    return normalized


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


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str] | None:
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        return None

    uri_without_scheme = gcs_uri[5:]
    if "/" not in uri_without_scheme:
        return None

    bucket_name, blob_name = uri_without_scheme.split("/", 1)
    if not bucket_name or not blob_name:
        return None

    return bucket_name, blob_name


def _generate_signed_read_url(gcs_uri: str) -> str | None:
    parsed = _parse_gcs_uri(gcs_uri)
    if not parsed:
        return None

    bucket_name, blob_name = parsed
    try:
        target_bucket = gcs_client.bucket(bucket_name)
        blob = target_bucket.blob(blob_name)
        return blob.generate_signed_url(
            version="v4",
            method="GET",
            expiration=timedelta(seconds=settings.SIGNED_URL_EXPIRY_SECONDS),
        )
    except Exception as exc:
        logger.warning("Failed to generate signed URL for '%s': %s", gcs_uri, str(exc))
        return None


def _is_valid_fallback_description(text: str) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False

    lowered = normalized.lower()
    lowered_compact = lowered.replace("-", "")
    if any(keyword in lowered or keyword in lowered_compact for keyword in FALLBACK_NOISE_KEYWORDS):
        return False

    digits = sum(ch.isdigit() for ch in normalized)
    letters = sum(ch.isalpha() for ch in normalized)
    if letters == 0 and digits >= max(6, int(len(normalized) * 0.5)):
        return False

    if re.fullmatch(r"[\d\W_]+", normalized):
        return False

    return True


def _normalize_date(value: object) -> str | None:
    if not value:
        return None
    candidate = str(value).strip()
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_positive_amount(value: object) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value)).strip()
    if cleaned in {"", ".", "-", "-."}:
        return None
    try:
        amount = float(cleaned)
    except ValueError:
        return None
    return round(amount, 2) if amount > 0 else None


def _is_numeric_only(value: str | None) -> bool:
    if not value:
        return False
    normalized = re.sub(r"\s+", "", value)
    if not normalized:
        return False
    return bool(re.fullmatch(r"[\d\W_]+", normalized))


def _validate_refined_result(
    refined_payload: dict | None,
    business_type: str,
) -> tuple[bool, dict, list[str]]:
    """
    Validate Gemini-refined OCR output against basic business rules.
    Returns (is_valid, normalized_data, quality_flags).
    """
    quality_flags: list[str] = []
    if not refined_payload:
        return False, {}, ["gemini_refine_empty"]

    try:
        allowed_categories = {
            category.id: category.name
            for category in get_categories_for_type(BusinessType(business_type))
        }
    except Exception:
        return False, {}, ["invalid_business_type"]

    raw_header = refined_payload.get("header", {})
    raw_items = refined_payload.get("items", [])
    if not isinstance(raw_header, dict) or not isinstance(raw_items, list):
        return False, {}, ["refine_shape_invalid"]

    normalized_items: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        amount = _parse_positive_amount(item.get("amount"))
        if not description or amount is None:
            continue
        if _is_valid_fallback_description(description) is False:
            quality_flags.append("refine_item_noise_removed")
            continue

        raw_category_id = item.get("category_id")
        category_id = str(raw_category_id).strip().upper() if raw_category_id else None
        if category_id and category_id not in allowed_categories:
            quality_flags.append("refine_invalid_category")
            category_id = None

        try:
            confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        if not category_id:
            rule_result = categorize_line_item_rule_only(description, business_type)
            category_id = rule_result.get("category_id")

        normalized_items.append(
            {
                "description": description,
                "amount": amount,
                "category_id": category_id,
                "category_name": allowed_categories.get(category_id, "Uncategorized")
                if category_id
                else "Uncategorized",
                "confidence": max(0.0, min(confidence, 1.0)),
            }
        )

    if not normalized_items:
        return False, {}, quality_flags + ["refine_no_valid_items"]

    normalized_date = _normalize_date(raw_header.get("date"))
    if raw_header.get("date") and not normalized_date:
        quality_flags.append("refine_header_invalid_date")

    merchant = str(raw_header.get("merchant", "")).strip() or None
    if _is_numeric_only(merchant):
        quality_flags.append("refine_header_merchant_numeric")

    parsed_total = _parse_positive_amount(raw_header.get("total"))
    items_total = round(sum(item["amount"] for item in normalized_items), 2)
    if parsed_total is None:
        parsed_total = items_total
        quality_flags.append("refine_header_total_missing")

    if abs(items_total - parsed_total) > max(3.0, items_total * 0.08):
        quality_flags.append("refine_total_mismatch")

    normalized_data = {
        "header": {
            "merchant": merchant,
            "date": normalized_date,
            "total": float(parsed_total),
        },
        "items": normalized_items,
        "items_total": items_total,
    }
    return True, normalized_data, quality_flags


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
        pipeline_started = time.perf_counter()
        extraction_mode = _normalize_extraction_mode(settings.RECEIPT_EXTRACTION_MODE)
        pipeline_path = "ocr_parser"
        quality_flags: list[str] = []
        ai_refined = False
        needs_review = False
        vision_ms = 0.0
        ocr_ms = 0.0
        ai_ms = 0.0
        vision_meta: dict = {}

        # 1. Upload to GCS
        upload_started = time.perf_counter()
        file_content = await file.read()
        await file.seek(0)  # Reset for GCS upload
        gcs_uri = await upload_to_gcs(file)
        upload_ms = round((time.perf_counter() - upload_started) * 1000, 2)

        # 2. Get Branch Info (to know if Coffee or Restaurant)
        branch_info = firestore_service.get_branch_config(branch_id)
        if not branch_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Branch '{branch_id}' not found.",
            )

        business_type = branch_info.get("type", "COFFEE")
        refined_data: dict | None = None
        ocr_data: dict = {"entities": [], "meta": {}}

        # 3. Vision-first extraction (fast path)
        if extraction_mode == "vision_first":
            vision_started = time.perf_counter()
            vision_payload = await ai_service.extract_receipt_from_image(
                image_bytes=file_content,
                mime_type=file.content_type or "",
                business_type=business_type,
                timeout_ms=settings.VISION_TIMEOUT_MS,
                max_retry=settings.VISION_MAX_RETRY,
            )
            vision_ms = round((time.perf_counter() - vision_started) * 1000, 2)
            is_vision_valid, normalized_vision, vision_flags = _validate_refined_result(
                refined_payload=vision_payload,
                business_type=business_type,
            )
            if isinstance(vision_payload, dict):
                raw_vision_meta = vision_payload.get("meta")
                if isinstance(raw_vision_meta, dict):
                    vision_meta = raw_vision_meta
            quality_flags.extend(vision_flags)
            if is_vision_valid:
                ai_refined = True
                refined_data = normalized_vision
                pipeline_path = "vision_direct"
            else:
                quality_flags.append("vision_fallback_to_ocr")

        # 4. OCR path (primary or fallback)
        if refined_data is None:
            ocr_started = time.perf_counter()
            ocr_data = ocr_service.process_invoice(file_content, file.content_type or "")
            ocr_ms = round((time.perf_counter() - ocr_started) * 1000, 2)
            pipeline_path = "ocr_parser"

            # Optional OCR-text refinement
            if settings.OCR_REFINEMENT_ENABLED:
                ai_started = time.perf_counter()
                refined_payload = await ai_service.refine_receipt_extraction(
                    full_text=str(ocr_data.get("text", "")),
                    business_type=business_type,
                    header_candidates=ocr_data.get("header_candidates"),
                    line_item_candidates=ocr_data.get("line_item_candidates"),
                )
                ai_ms = round((time.perf_counter() - ai_started) * 1000, 2)
                is_refined_valid, normalized_refined, refine_flags = _validate_refined_result(
                    refined_payload=refined_payload,
                    business_type=business_type,
                )
                quality_flags.extend(refine_flags)
                if is_refined_valid:
                    ai_refined = True
                    refined_data = normalized_refined
                    pipeline_path = "ocr_refined"
                else:
                    needs_review = True

        # 5. Build draft items
        enriched_items = []
        ocr_header = ocr_data.get("header", {}) if isinstance(ocr_data.get("header"), dict) else {}
        header = {
            "merchant": ocr_header.get("merchant"),
            "date": _normalize_date(ocr_header.get("date")) if ocr_header.get("date") else None,
            "total": float(_parse_positive_amount(ocr_header.get("total")) or 0.0),
        }

        if refined_data:
            header = refined_data["header"]
            for idx, item in enumerate(refined_data["items"]):
                enriched_items.append(
                    {
                        "id": f"item_{idx + 1}",
                        "description": item["description"],
                        "amount": float(item["amount"]),
                        "category_id": item["category_id"],
                        "category_name": item["category_name"],
                        "confidence": max(0.6, float(item.get("confidence", 0.0))),
                        "is_manual_edit": False,
                    }
                )
        else:
            # Deterministic parser path
            category_mapper = (
                categorize_line_item_rule_only
                if settings.OCR_REFINEMENT_ENABLED
                else categorize_line_item
            )
            ocr_line_items = ocr_data.get("line_items", [])
            for idx, extracted_item in enumerate(ocr_line_items):
                description = str(extracted_item.get("description", "")).strip()
                if not description:
                    continue

                cat_result = (
                    category_mapper(description, business_type)
                    if category_mapper is categorize_line_item_rule_only
                    else await category_mapper(description, business_type)
                )
                extracted_amount = _parse_positive_amount(extracted_item.get("amount"))
                if extracted_amount is None:
                    continue

                enriched_items.append(
                    {
                        "id": f"item_{idx + 1}",
                        "description": description,
                        "amount": extracted_amount,
                        "category_id": cat_result.get("category_id"),
                        "category_name": cat_result.get("category_name"),
                        "confidence": float(cat_result.get("confidence", 0.0)),
                        "is_manual_edit": False,
                    }
                )

        # Fallback: if structured line extraction returns nothing, keep lightweight
        # textual items instead of returning an empty draft.
        if not enriched_items:
            needs_review = True
            quality_flags.append("fallback_entity_items")
            for idx, entity in enumerate(ocr_data.get("entities", [])):
                description = str(entity.get("mention_text", "")).strip()
                if not _is_valid_fallback_description(description):
                    continue

                cat_result = (
                    categorize_line_item_rule_only(description, business_type)
                    if settings.OCR_REFINEMENT_ENABLED
                    else await categorize_line_item(description, business_type)
                )
                enriched_items.append({
                    "id": f"item_{idx + 1}",
                    "description": description,
                    "amount": 0.0,
                    "category_id": cat_result.get("category_id"),
                    "category_name": cat_result.get("category_name"),
                    "confidence": cat_result.get("confidence", 0.0),
                    "is_manual_edit": False,
                })

                if len(enriched_items) >= 20:
                    break

        items_total = round(sum(float(item.get("amount", 0.0)) for item in enriched_items), 2)
        header_total = _parse_positive_amount(header.get("total"))
        if header_total is None:
            header_total = items_total
            quality_flags.append("header_total_autofill_items_sum")
        if items_total > 0 and abs(items_total - header_total) > max(3.0, items_total * 0.08):
            needs_review = True
            quality_flags.append("header_total_items_mismatch")

        header["total"] = float(header_total)
        if _is_numeric_only(header.get("merchant")):
            needs_review = True
            quality_flags.append("header_merchant_numeric")
        if header.get("date") is None:
            needs_review = True
            quality_flags.append("header_date_missing")

        # 6. Save Draft to Firestore
        total_ms = round((time.perf_counter() - pipeline_started) * 1000, 2)
        receipt_doc = {
            "branch_id": branch_id,
            "user_id": current_user["uid"],
            "status": "DRAFT",
            "image_url": gcs_uri,
            "header": header,
            "items": enriched_items,
            "ocr_version": (
                "v4_vision_direct"
                if pipeline_path == "vision_direct"
                else ("v3_refined" if pipeline_path == "ocr_refined" else "v2_parser")
            ),
            "ai_refined": ai_refined,
            "needs_review": needs_review,
            "quality_flags": sorted(set(quality_flags)),
            "processing_meta": {
                "timings_ms": {
                    "upload": upload_ms,
                    "vision_extract": vision_ms,
                    "ocr": ocr_ms,
                    "ai_refine": ai_ms,
                    "total": total_ms,
                },
                "pipeline": {
                    "mode": extraction_mode,
                    "path": pipeline_path,
                    "vision_attempted": extraction_mode == "vision_first",
                    "ocr_refinement_enabled": settings.OCR_REFINEMENT_ENABLED,
                },
                "vision_meta": vision_meta,
                "ocr_meta": ocr_data.get("meta", {}),
            },
        }

        saved_receipt = firestore_service.create_receipt(receipt_doc)
        logger.info(
            "receipt_upload_processed receipt_id=%s branch_id=%s items=%d path=%s ai_refined=%s needs_review=%s timings_ms=%s flags=%s",
            saved_receipt["id"],
            branch_id,
            len(enriched_items),
            pipeline_path,
            ai_refined,
            needs_review,
            receipt_doc["processing_meta"]["timings_ms"],
            receipt_doc["quality_flags"],
        )

        return {
            "receipt_id": saved_receipt["id"],
            "status": saved_receipt["status"],
            "items": saved_receipt["items"],
            "processing_path": pipeline_path,
            "needs_review": saved_receipt.get("needs_review", False),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process receipt: {str(e)}",
        )


# =====================================================
# 2. GET / — List Receipts
# =====================================================

@router.get("")
async def list_receipts(
    status_filter: str | None = Query(None, alias="status"),
    branch_id: str | None = Query(None),
    only_mine: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    include_preview: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """
    List receipts with optional status/branch filters.
    """
    normalized_status = _normalize_receipt_status(status_filter)
    if status_filter and normalized_status is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status filter. Allowed: DRAFT, VERIFIED, REJECTED.",
        )

    user_filter = current_user["uid"] if only_mine else None
    receipts = firestore_service.list_receipts(
        status=normalized_status,
        branch_id=branch_id,
        user_id=user_filter,
        limit=limit,
    )

    if include_preview:
        for receipt in receipts:
            image_url = receipt.get("image_url")
            receipt["image_preview_url"] = (
                _generate_signed_read_url(image_url) if isinstance(image_url, str) else None
            )

    return {
        "receipts": receipts,
        "count": len(receipts),
    }


# =====================================================
# 3. GET /{receipt_id} — Get Receipt Detail
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

    image_url = receipt.get("image_url")
    receipt["image_preview_url"] = (
        _generate_signed_read_url(image_url) if isinstance(image_url, str) else None
    )

    return receipt


# =====================================================
# 4. PUT /{receipt_id}/verify — Verify & Submit
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

    existing_status = str(existing.get("status", "")).upper()
    if existing_status == "VERIFIED":
        if existing.get("bigquery_synced", False):
            return {
                "receipt_id": receipt_id,
                "status": "VERIFIED",
                "message": "Receipt already verified. Skipped duplicate save.",
                "bigquery_rows_inserted": 0,
                "already_verified": True,
            }

        # Allow retrying BigQuery sync for previously verified receipts.
        try:
            rows_inserted = bigquery_service.insert_verified_receipt(existing)
            firestore_service.update_receipt_fields(
                receipt_id=receipt_id,
                fields={
                    "bigquery_synced": True,
                    "bigquery_rows_inserted": rows_inserted,
                    "bigquery_synced_at": datetime.utcnow().isoformat(),
                    "bigquery_sync_error": None,
                },
            )
        except Exception as exc:
            firestore_service.update_receipt_fields(
                receipt_id=receipt_id,
                fields={
                    "bigquery_synced": False,
                    "bigquery_sync_error": str(exc),
                },
            )
            rows_inserted = 0

        return {
            "receipt_id": receipt_id,
            "status": "VERIFIED",
            "message": "Receipt already verified. BigQuery sync retried.",
            "bigquery_rows_inserted": rows_inserted,
            "already_verified": True,
        }

    # Validate total_check matches sum of items
    items_total = sum(item.amount for item in verified_data.items)
    if abs(items_total - verified_data.total_check) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Total check ({verified_data.total_check}) does not match "
                   f"sum of items ({items_total}).",
        )

    branch_info = firestore_service.get_branch_config(existing.get("branch_id", ""))
    business_type = branch_info.get("type", "COFFEE") if branch_info else "COFFEE"
    category_map = {
        category.id: category.name
        for category in get_categories_for_type(BusinessType(business_type))
    }

    verified_items = []
    for item in verified_data.items:
        normalized_category_id = item.category_id.strip().upper()
        if normalized_category_id not in category_map:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid category_id '{item.category_id}' for branch type {business_type}.",
            )
        verified_items.append(
            {
                "description": item.description,
                "amount": item.amount,
                "category_id": normalized_category_id,
                "category_name": category_map[normalized_category_id],
            }
        )

    # Convert verified payload to Firestore structure
    update_payload = {
        "items": verified_items,
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
        firestore_service.update_receipt_fields(
            receipt_id=receipt_id,
            fields={
                "bigquery_synced": True,
                "bigquery_rows_inserted": rows_inserted,
                "bigquery_synced_at": datetime.utcnow().isoformat(),
                "bigquery_sync_error": None,
            },
        )
    except Exception as exc:
        # Log but don't fail — Firestore is already updated
        firestore_service.update_receipt_fields(
            receipt_id=receipt_id,
            fields={
                "bigquery_synced": False,
                "bigquery_sync_error": str(exc),
            },
        )
        rows_inserted = 0

    return {
        "receipt_id": receipt_id,
        "status": "VERIFIED",
        "message": "Receipt verified and saved successfully.",
        "bigquery_rows_inserted": rows_inserted,
        "already_verified": False,
    }
