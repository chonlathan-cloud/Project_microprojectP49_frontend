import uuid
import logging
import re
import time
import mimetypes
from datetime import datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query, status
from fastapi.responses import Response
from google.cloud import storage

from app.core.config import settings
from app.core.security import get_current_user
from app.models.branch import get_categories_for_type
from app.models.receipt import BusinessType, ReceiptVerify, ReceiptVerifyFlowAccount
from app.services import (
    ai_service,
    bigquery_service,
    firestore_service,
    flowaccount_service,
    ocr_service,
)
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
VAT_DESCRIPTION_TOKENS = ("vat", "tax", "ภาษี")
ADJUSTMENT_TYPE_KEYWORDS = {
    "discount": ("discount", "ส่วนลด"),
    "service_charge": ("service charge", "service", "ค่าบริการ"),
    "rounding": ("rounding", "round off", "ปัดเศษ"),
}
FLOWACCOUNT_SYNC_ROLES = {"admin", "executive"}


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


def _resolve_receipt_preview_url(image_url: str | None) -> str | None:
    if not image_url:
        return None
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    # For gs:// objects, only return signed URL.
    # Do not fallback to public storage URL because private buckets return 403.
    return _generate_signed_read_url(image_url)


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


def _normalize_optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _split_raw_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line and line.strip()]


def _extract_last_amount_from_line(text: str) -> float | None:
    matches = re.findall(r"(-?\d[\d,]*\.?\d{0,2})", str(text or ""))
    if not matches:
        return None
    return _parse_positive_amount(matches[-1])


def _normalize_adjustment_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"discount", "service_charge", "rounding", "other"}:
        return normalized

    for adjustment_type, keywords in ADJUSTMENT_TYPE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return adjustment_type

    return None


def _is_numeric_only(value: str | None) -> bool:
    if not value:
        return False
    normalized = re.sub(r"\s+", "", value)
    if not normalized:
        return False
    return bool(re.fullmatch(r"[\d\W_]+", normalized))


def _contains_vat_keyword(text: str | None) -> bool:
    if not text:
        return False
    normalized = str(text).strip().lower()
    return any(token in normalized for token in VAT_DESCRIPTION_TOKENS)


def _infer_document_type(raw_text: str) -> str | None:
    normalized = str(raw_text or "").lower()
    has_receipt = "ใบเสร็จ" in normalized or "receipt" in normalized
    has_tax_invoice = "ใบกำกับภาษี" in normalized or "tax invoice" in normalized
    if has_receipt and has_tax_invoice:
        return "receipt_and_tax_invoice"
    if has_tax_invoice:
        return "tax_invoice"
    if has_receipt:
        return "receipt"
    return None


def _extract_first_matching_line(raw_lines: list[str], keywords: tuple[str, ...]) -> str | None:
    for line in raw_lines:
        normalized = line.lower()
        if any(keyword in normalized for keyword in keywords):
            return line.strip()
    return None


def _strip_label_prefix(value: str, labels: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    for label in labels:
        text = re.sub(
            rf"^\s*{re.escape(label)}\s*[:：]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
    return text


def _extract_labeled_party_block(raw_lines: list[str], labels: tuple[str, ...]) -> dict:
    start_index = -1
    for index, line in enumerate(raw_lines):
        normalized = line.lower()
        if any(label.lower() in normalized for label in labels):
            start_index = index
            break
    if start_index < 0:
        return {}

    block_lines = raw_lines[start_index : start_index + 8]
    block_text = "\n".join(block_lines)
    legal_name = None
    address_parts: list[str] = []

    for index, line in enumerate(block_lines):
        candidate = _strip_label_prefix(line, labels)
        normalized = candidate.lower()
        if not legal_name and any(
            token in normalized
            for token in ("บริษัท", "จำกัด", "limited", "co.", "ltd", "หจก")
        ):
            legal_name = candidate
            continue
        if legal_name:
            if any(
                token in normalized
                for token in (
                    "ชื่อลูกค้า",
                    "ลูกค้า",
                    "ผู้ซื้อ",
                    "buyer",
                    "customer",
                    "ลำดับ",
                    "รายการสินค้า",
                    "จำนวน",
                    "ราคา",
                    "รวมเงิน",
                    "หมายเหตุ",
                    "การชำระเงิน",
                )
            ):
                break
            if any(
                token in normalized
                for token in (
                    "เลขประจำตัวผู้เสียภาษี",
                    "เลขประจำผู้เสียภาษี",
                    "เลขที่เสียภาษี",
                    "เลขผู้เสียภาษี",
                    "tax id",
                    "เบอร์โทรศัพท์",
                    "เบอร์โทร",
                    "โทร",
                    "tel",
                    "อีเมล",
                    "อีเมล์",
                    "email",
                    "ผู้ติดต่อ",
                    "contact",
                )
            ):
                continue
            if index > 0:
                address_candidate = _strip_label_prefix(candidate, ("ที่อยู่", "address"))
                if address_candidate:
                    address_parts.append(address_candidate)

    tax_id_match = re.search(
        r"(?:เลขประจำตัวผู้เสียภาษี|เลขประจำผู้เสียภาษี|เลขที่เสียภาษี|เลขผู้เสียภาษี|tax id)[^\d]*(\d{10,13})",
        block_text,
        flags=re.IGNORECASE,
    ) or re.search(r"\b\d{13}\b", block_text)
    phone_match = re.search(
        r"(?:เบอร์โทรศัพท์|เบอร์โทร|โทร\.?|tel\.?|phone)[^\d]*(\d[\d\- ]{6,})",
        block_text,
        flags=re.IGNORECASE,
    )
    email_match = re.search(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        block_text,
        flags=re.IGNORECASE,
    )
    contact_match = re.search(
        r"(?:ผู้ติดต่อ|contact)\s*[:：]?\s*([^\n]+)",
        block_text,
        flags=re.IGNORECASE,
    )

    return {
        "legal_name": legal_name,
        "tax_id": _first_regex_value(tax_id_match),
        "phone": re.sub(r"\s+", "", _first_regex_value(phone_match) or "")
        or None,
        "email": email_match.group(0) if email_match else None,
        "contact_person": _first_regex_value(contact_match),
        "address": " ".join(address_parts) if address_parts else None,
    }


def _first_regex_value(match: re.Match[str] | None) -> str | None:
    if not match:
        return None
    if match.lastindex:
        return match.group(1)
    return match.group(0)


def _normalize_party_payload(value: object) -> dict:
    if not isinstance(value, dict):
        value = {}
    return {
        "brand_name": _normalize_optional_text(value.get("brand_name")),
        "legal_name": _normalize_optional_text(value.get("legal_name")),
        "branch_name": _normalize_optional_text(value.get("branch_name")),
        "tax_id": _normalize_optional_text(value.get("tax_id")),
        "contact_person": _normalize_optional_text(value.get("contact_person")),
        "email": _normalize_optional_text(value.get("email")),
        "phone": _normalize_optional_text(value.get("phone")),
        "address": _normalize_optional_text(value.get("address")),
    }


def _extract_financial_value(raw_lines: list[str], keywords: tuple[str, ...]) -> float | None:
    line = _extract_first_matching_line(raw_lines, keywords)
    if not line:
        return None
    return _extract_last_amount_from_line(line)


def _infer_seller_payload(
    header: dict,
    document_context: dict,
    raw_lines: list[str],
    raw_text: str,
    gemini_seller: dict | None = None,
) -> dict:
    normalized_gemini_seller = _normalize_party_payload(gemini_seller)
    labeled_seller = _extract_labeled_party_block(
        raw_lines,
        ("ผู้ขาย", "ผู้ออก", "ผู้ออกใบเสร็จ", "supplier", "vendor", "dealer"),
    )
    legal_name = None
    address_parts: list[str] = []
    legal_name_index = -1

    for index, line in enumerate(raw_lines[:12]):
        normalized = line.lower()
        if any(token in normalized for token in ("บริษัท", "จำกัด", "limited", "co.", "ltd", "หจก")):
            legal_name = line
            legal_name_index = index
            break

    if legal_name_index >= 0:
        for line in raw_lines[legal_name_index + 1 : legal_name_index + 6]:
            normalized = line.lower()
            if any(
                stop_token in normalized
                for stop_token in (
                    "เลขประจำตัวผู้เสียภาษี",
                    "เลขประจำผู้เสียภาษี",
                    "เลขที่เสียภาษี",
                    "เลขผู้เสียภาษี",
                    "tax id",
                    "เบอร์โทรศัพท์",
                    "โทร",
                    "tel",
                    "ใบกำกับภาษี",
                    "receipt",
                    "invoice",
                    "พนักงานขาย",
                    "วันที่",
                    "ชื่อลูกค้า",
                    "ลูกค้า",
                    "ผู้ซื้อ",
                    "buyer",
                    "customer",
                    "ลำดับ",
                    "รายการสินค้า",
                    "จำนวน",
                    "ราคา",
                    "รวมเงิน",
                    "หมายเหตุ",
                    "การชำระเงิน",
                )
            ):
                break
            address_candidate = _strip_label_prefix(line, ("ที่อยู่", "address"))
            if address_candidate:
                address_parts.append(address_candidate)

    tax_id_match = re.search(
        r"(?:เลขประจำตัวผู้เสียภาษี|เลขประจำผู้เสียภาษี|เลขที่เสียภาษี|เลขผู้เสียภาษี|tax id)[^\d]*(\d{10,13})",
        raw_text,
        flags=re.IGNORECASE,
    ) or re.search(r"\b\d{13}\b", raw_text)
    phone_match = re.search(
        r"(?:เบอร์โทรศัพท์|เบอร์โทร|โทร\.?|tel\.?|phone)[^\d]*(\d[\d\- ]{6,})",
        raw_text,
        flags=re.IGNORECASE,
    )

    tax_id = _first_regex_value(tax_id_match)
    phone = _first_regex_value(phone_match)
    email_match = re.search(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        raw_text,
        flags=re.IGNORECASE,
    )
    contact_line = _extract_first_matching_line(raw_lines, ("ผู้ติดต่อ", "contact"))

    return {
        "brand_name": (
            normalized_gemini_seller.get("brand_name")
            or _normalize_optional_text(header.get("merchant"))
        ),
        "legal_name": (
            normalized_gemini_seller.get("legal_name")
            or labeled_seller.get("legal_name")
            or legal_name
        ),
        "branch_name": (
            normalized_gemini_seller.get("branch_name")
            or _normalize_optional_text(document_context.get("store_branch"))
            or _extract_first_matching_line(raw_lines, ("สำนักงานใหญ่", "สาขา"))
        ),
        "tax_id": normalized_gemini_seller.get("tax_id")
        or labeled_seller.get("tax_id")
        or tax_id,
        "contact_person": (
            normalized_gemini_seller.get("contact_person")
            or labeled_seller.get("contact_person")
            or (
                re.sub(r"^(?:ผู้ติดต่อ|contact)\s*[:：]?\s*", "", contact_line, flags=re.IGNORECASE).strip()
                if contact_line
                else None
            )
        ),
        "email": normalized_gemini_seller.get("email")
        or labeled_seller.get("email")
        or (email_match.group(0) if email_match else None),
        "phone": normalized_gemini_seller.get("phone")
        or labeled_seller.get("phone")
        or (re.sub(r"\s+", "", phone) if phone else None),
        "address": normalized_gemini_seller.get("address")
        or labeled_seller.get("address")
        or (" ".join(address_parts) if address_parts else None),
    }


def _infer_document_numbers(document_context: dict, raw_lines: list[str], raw_text: str) -> dict:
    fallback_document_number = None
    for line in raw_lines:
        stripped = line.strip()
        if re.fullmatch(r"[A-Z]{1,5}\d{6,}", stripped):
            fallback_document_number = stripped
            break

    generic_match = re.search(r"\b[A-Z]{1,5}\d{6,}\b", raw_text)
    if not fallback_document_number and generic_match:
        fallback_document_number = generic_match.group(0)

    return {
        "invoice_number": (
            _normalize_optional_text(document_context.get("invoice_number"))
            or fallback_document_number
        ),
        "receipt_number": _normalize_optional_text(document_context.get("receipt_number")),
        "tax_invoice_number": _normalize_optional_text(document_context.get("tax_invoice_number")),
        "due_date": _normalize_date(document_context.get("due_date")),
        "payment_reference": _normalize_optional_text(document_context.get("payment_reference")),
    }


def _normalize_adjustment_payload(raw_adjustment: dict) -> dict | None:
    if not isinstance(raw_adjustment, dict):
        return None

    adjustment_type = _normalize_adjustment_type(raw_adjustment.get("type"))
    label = str(raw_adjustment.get("label", "")).strip()
    amount = _parse_positive_amount(raw_adjustment.get("amount"))
    if not adjustment_type or not label or amount is None:
        return None

    return {
        "type": adjustment_type,
        "label": label,
        "amount": amount,
        "raw_text": _normalize_optional_text(raw_adjustment.get("raw_text")),
    }


def _infer_adjustments_payload(raw_lines: list[str], gemini_payload: dict | None) -> list[dict]:
    raw_adjustments = gemini_payload.get("adjustments", []) if isinstance(gemini_payload, dict) else []
    normalized_adjustments: list[dict] = []

    if isinstance(raw_adjustments, list):
        for raw_adjustment in raw_adjustments:
            normalized_adjustment = _normalize_adjustment_payload(raw_adjustment)
            if normalized_adjustment:
                normalized_adjustments.append(normalized_adjustment)

    if normalized_adjustments:
        return normalized_adjustments

    inferred_adjustments: list[dict] = []
    for line in raw_lines:
        normalized_line = line.lower()
        adjustment_type = None
        for candidate_type, keywords in ADJUSTMENT_TYPE_KEYWORDS.items():
            if any(keyword in normalized_line for keyword in keywords):
                adjustment_type = candidate_type
                break

        if not adjustment_type:
            continue

        amount = _extract_last_amount_from_line(line)
        if amount is None:
            continue

        label = re.sub(r"\s+[-+]?\d[\d,]*\.?\d{0,2}\s*$", "", line).strip(" -:")
        inferred_adjustments.append(
            {
                "type": adjustment_type,
                "label": label or line.strip(),
                "amount": amount,
                "raw_text": line.strip(),
            }
        )

    unique_adjustments: list[dict] = []
    seen_keys: set[tuple[str, str, float]] = set()
    for adjustment in inferred_adjustments:
        dedupe_key = (
            adjustment["type"],
            adjustment["label"],
            float(adjustment["amount"]),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        unique_adjustments.append(adjustment)

    return unique_adjustments


def _infer_financial_summary(
    header: dict,
    raw_lines: list[str],
    raw_text: str,
    adjustments: list[dict],
    gemini_payload: dict | None,
) -> dict:
    raw_summary = gemini_payload.get("financial_summary", {}) if isinstance(gemini_payload, dict) else {}
    discount_amount = None
    for adjustment in adjustments:
        if adjustment.get("type") == "discount":
            discount_amount = round((discount_amount or 0.0) + float(adjustment.get("amount", 0.0)), 2)

    subtotal = _parse_positive_amount(raw_summary.get("subtotal")) if isinstance(raw_summary, dict) else None
    net_amount = _parse_positive_amount(raw_summary.get("net_amount")) if isinstance(raw_summary, dict) else None
    amount_before_vat = (
        _parse_positive_amount(raw_summary.get("amount_before_vat"))
        if isinstance(raw_summary, dict)
        else None
    )
    vat_amount = _parse_positive_amount(raw_summary.get("vat_amount")) if isinstance(raw_summary, dict) else None
    grand_total = _parse_positive_amount(raw_summary.get("grand_total")) if isinstance(raw_summary, dict) else None
    vat_included = bool(raw_summary.get("vat_included")) if isinstance(raw_summary, dict) else False

    subtotal = subtotal or _extract_financial_value(raw_lines, ("รวมเป็นเงิน", "subtotal"))
    if discount_amount is None:
        discount_amount = _extract_financial_value(raw_lines, ("ส่วนลด", "discount"))
    net_amount = net_amount or _extract_financial_value(raw_lines, ("จำนวนเงินหลังหักส่วนลด", "after discount", "net amount"))
    amount_before_vat = amount_before_vat or _extract_financial_value(
        raw_lines,
        ("ราคารวมก่อนภาษีมูลค่าเพิ่ม", "before vat", "before tax"),
    )
    vat_amount = vat_amount or _parse_positive_amount(header.get("vat")) or _extract_financial_value(
        raw_lines,
        ("ภาษีมูลค่าเพิ่ม", "vat"),
    )
    grand_total = grand_total or _parse_positive_amount(header.get("total")) or _extract_financial_value(
        raw_lines,
        ("รวมทั้งสิ้น", "grand total", "total due"),
    )
    if "vat included" in raw_text.lower():
        vat_included = True

    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "net_amount": net_amount,
        "amount_before_vat": amount_before_vat,
        "vat_amount": vat_amount,
        "grand_total": grand_total,
        "vat_included": vat_included,
    }


def _build_field_confidence(
    header: dict,
    document_numbers: dict,
    seller: dict,
    confidence_summary: dict,
) -> dict:
    try:
        overall_confidence = float(confidence_summary.get("overall", 0.0) or 0.0)
    except (TypeError, ValueError):
        overall_confidence = 0.0

    def confidence_for(value: object, fallback: float = 0.0) -> float:
        return round(overall_confidence, 2) if value not in (None, "", []) else fallback

    return {
        "merchant": confidence_for(header.get("merchant")),
        "date": confidence_for(header.get("date")),
        "total": confidence_for(header.get("total")),
        "vat": confidence_for(header.get("vat"), 0.0),
        "invoice_number": confidence_for(document_numbers.get("invoice_number")),
        "receipt_number": confidence_for(document_numbers.get("receipt_number")),
        "tax_invoice_number": confidence_for(document_numbers.get("tax_invoice_number")),
        "seller_tax_id": confidence_for(seller.get("tax_id")),
        "seller_phone": confidence_for(seller.get("phone")),
        "seller_email": confidence_for(seller.get("email")),
        "seller_address": confidence_for(seller.get("address")),
        "seller_contact_person": confidence_for(seller.get("contact_person")),
    }


def _build_receipt_adjustments(adjustments: list[dict]) -> list[dict]:
    receipt_adjustments: list[dict] = []
    for index, adjustment in enumerate(adjustments):
        receipt_adjustments.append(
            {
                "id": f"adj_{index + 1}",
                "type": adjustment.get("type"),
                "label": adjustment.get("label"),
                "amount": float(adjustment.get("amount", 0.0)),
                "is_manual_edit": False,
            }
        )
    return receipt_adjustments


def _get_signed_adjustment_total(adjustments: list[dict]) -> float:
    signed_total = 0.0
    for adjustment in adjustments:
        amount = float(adjustment.get("amount", 0.0) or 0.0)
        adjustment_type = str(adjustment.get("type", "")).strip().lower()
        if adjustment_type == "discount":
            signed_total -= amount
        else:
            signed_total += amount
    return round(signed_total, 2)


def _append_vat_item_if_missing(
    items: list[dict],
    header: dict,
    business_type: str,
) -> list[dict]:
    vat_amount = float(_parse_positive_amount(header.get("vat")) or 0.0)
    if vat_amount <= 0:
        return items

    for item in items:
        description = str(item.get("description", ""))
        if _contains_vat_keyword(description):
            # Existing VAT-like line already present.
            return items

    default_category_id = None
    if business_type == BusinessType.COFFEE.value:
        default_category_id = "C8"
    elif business_type == BusinessType.RESTAURANT.value:
        default_category_id = "F7"

    category_map = {
        category.id: category.name
        for category in get_categories_for_type(BusinessType(business_type))
    }
    if default_category_id not in category_map:
        default_category_id = None

    vat_item = {
        "id": f"item_{len(items) + 1}",
        "description": "VAT (ภาษีมูลค่าเพิ่ม)",
        "amount": round(vat_amount, 2),
        "category_id": default_category_id,
        "category_name": category_map.get(default_category_id, "Uncategorized"),
        "confidence": 0.95,
        "is_manual_edit": False,
    }
    return [*items, vat_item]


def _build_ocr_by_gemini_payload(
    pipeline_path: str,
    gemini_payload: dict | None,
    ocr_data: dict,
) -> dict:
    ocr_text = str(ocr_data.get("text", "") or "").strip()
    raw_lines = _split_raw_lines(ocr_text)[:200]
    gemini_payload = gemini_payload if isinstance(gemini_payload, dict) else {}

    header = gemini_payload.get("header", {})
    if not isinstance(header, dict):
        header = {}
    confidence_summary = gemini_payload.get("confidence_summary", {})
    if not isinstance(confidence_summary, dict):
        confidence_summary = {}
    document_context = gemini_payload.get("document_context", {})
    if not isinstance(document_context, dict):
        document_context = {}
    gemini_seller = gemini_payload.get("seller", {})
    if not isinstance(gemini_seller, dict):
        gemini_seller = {}
    gemini_buyer = gemini_payload.get("buyer", {})
    if not isinstance(gemini_buyer, dict):
        gemini_buyer = {}
    meta = gemini_payload.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}

    adjustments = _infer_adjustments_payload(raw_lines, gemini_payload)
    seller = _infer_seller_payload(
        header=header,
        document_context=document_context,
        raw_lines=raw_lines,
        raw_text=ocr_text,
        gemini_seller=gemini_seller,
    )
    buyer = _normalize_party_payload(gemini_buyer)
    document_numbers = _infer_document_numbers(
        document_context=document_context,
        raw_lines=raw_lines,
        raw_text=ocr_text,
    )
    financial_summary = _infer_financial_summary(
        header=header,
        raw_lines=raw_lines,
        raw_text=ocr_text,
        adjustments=adjustments,
        gemini_payload=gemini_payload,
    )
    extraction_notes = []
    extraction_notes.extend(confidence_summary.get("notes", []) if isinstance(confidence_summary.get("notes"), list) else [])
    extraction_notes.extend(document_context.get("notes", []) if isinstance(document_context.get("notes"), list) else [])

    return {
        "schema_version": 2,
        "pipeline_path": pipeline_path,
        "document_type": (
            _normalize_optional_text(gemini_payload.get("document_type"))
            or _infer_document_type(ocr_text)
        ),
        "seller": seller,
        "buyer": buyer,
        "document_numbers": document_numbers,
        "staff_or_cashier_name": (
            _normalize_optional_text(gemini_payload.get("staff_or_cashier_name"))
            or _extract_first_matching_line(raw_lines, ("พนักงานขาย", "cashier", "seller"))
        ),
        "financial_summary": financial_summary,
        "adjustments": adjustments,
        "header": {
            "merchant": _normalize_optional_text(header.get("merchant")),
            "date": _normalize_date(header.get("date")),
            "total": float(_parse_positive_amount(header.get("total")) or 0.0),
            "vat": float(_parse_positive_amount(header.get("vat")) or 0.0),
        },
        "items": gemini_payload.get("items", []) if isinstance(gemini_payload.get("items"), list) else [],
        "raw_text": ocr_text[:20000],
        "raw_lines": raw_lines,
        "field_confidence": _build_field_confidence(
            header=header,
            document_numbers=document_numbers,
            seller=seller,
            confidence_summary=confidence_summary,
        ),
        "confidence_summary": confidence_summary,
        "extraction_notes": sorted({str(note).strip() for note in extraction_notes if str(note).strip()}),
        "meta": {
            "captured_at": datetime.utcnow().isoformat(),
            "source": _normalize_optional_text(gemini_payload.get("source")),
            "gemini": meta,
            "ocr": ocr_data.get("meta", {}) if isinstance(ocr_data.get("meta"), dict) else {},
        },
    }


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
        is_vat_line = _contains_vat_keyword(description)
        if not is_vat_line and _is_valid_fallback_description(description) is False:
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
    parsed_vat = _parse_positive_amount(raw_header.get("vat"))
    items_total = round(sum(item["amount"] for item in normalized_items), 2)
    if parsed_total is None:
        parsed_total = items_total
        quality_flags.append("refine_header_total_missing")
    if parsed_vat is None:
        parsed_vat = 0.0

    if abs(items_total - parsed_total) > max(3.0, items_total * 0.08):
        quality_flags.append("refine_total_mismatch")
    if parsed_vat > parsed_total:
        quality_flags.append("refine_vat_exceeds_total")
        parsed_vat = 0.0

    normalized_data = {
        "header": {
            "merchant": merchant,
            "date": normalized_date,
            "total": float(parsed_total),
            "vat": float(parsed_vat),
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
        vision_payload_raw: dict | None = None
        refined_payload_raw: dict | None = None

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
            if isinstance(vision_payload, dict):
                vision_payload_raw = vision_payload
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
                if isinstance(refined_payload, dict):
                    refined_payload_raw = refined_payload
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
            "vat": float(_parse_positive_amount(ocr_header.get("vat")) or 0.0),
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
        if float(header.get("vat", 0.0) or 0.0) > float(header.get("total", 0.0) or 0.0):
            needs_review = True
            quality_flags.append("header_vat_exceeds_total")
            header["vat"] = 0.0

        # Ensure VAT is represented as a line item when available.
        enriched_items = _append_vat_item_if_missing(
            items=enriched_items,
            header=header,
            business_type=business_type,
        )

        ocr_by_gemini = _build_ocr_by_gemini_payload(
            pipeline_path=pipeline_path,
            gemini_payload=vision_payload_raw or refined_payload_raw,
            ocr_data=ocr_data,
        )

        # 6. Save Draft to Firestore
        total_ms = round((time.perf_counter() - pipeline_started) * 1000, 2)
        receipt_doc = {
            "branch_id": branch_id,
            "user_id": current_user["uid"],
            "status": "DRAFT",
            "image_url": gcs_uri,
            "header": header,
            "seller": ocr_by_gemini.get("seller")
            if isinstance(ocr_by_gemini.get("seller"), dict)
            else {},
            "buyer": ocr_by_gemini.get("buyer")
            if isinstance(ocr_by_gemini.get("buyer"), dict)
            else {},
            "items": enriched_items,
            "adjustments": _build_receipt_adjustments(
                ocr_by_gemini.get("adjustments", [])
                if isinstance(ocr_by_gemini.get("adjustments"), list)
                else []
            ),
            "ocr_version": (
                "v4_vision_direct"
                if pipeline_path == "vision_direct"
                else ("v3_refined" if pipeline_path == "ocr_refined" else "v2_parser")
            ),
            "OCRbyGemini": ocr_by_gemini,
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
        logger.exception("receipt_upload_failed branch_id=%s", branch_id)
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
                _resolve_receipt_preview_url(image_url) if isinstance(image_url, str) else None
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
        _resolve_receipt_preview_url(image_url) if isinstance(image_url, str) else None
    )

    branch_id = str(receipt.get("branch_id", "")).strip()
    branch_type = BusinessType.RESTAURANT.value
    allowed_categories = []
    if branch_id:
        branch = firestore_service.get_branch_config(branch_id)
        if branch and branch.get("type"):
            branch_type_raw = str(branch.get("type")).upper()
            if branch_type_raw in {BusinessType.COFFEE.value, BusinessType.RESTAURANT.value}:
                branch_type = branch_type_raw
        allowed_categories = [
            {"id": category.id, "name": category.name}
            for category in get_categories_for_type(BusinessType(branch_type))
        ]

    receipt["branch_type"] = branch_type
    receipt["allowed_categories"] = allowed_categories
    receipt["items"] = _append_vat_item_if_missing(
        items=list(receipt.get("items", [])),
        header=receipt.get("header", {}) if isinstance(receipt.get("header"), dict) else {},
        business_type=branch_type,
    )
    receipt["adjustments"] = (
        list(receipt.get("adjustments", []))
        if isinstance(receipt.get("adjustments"), list)
        else []
    )

    return receipt


# =====================================================
# 3.1 GET /{receipt_id}/preview — Authenticated Image Proxy
# =====================================================

@router.get("/{receipt_id}/preview")
async def get_receipt_preview(
    receipt_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Return receipt image bytes via backend auth path.
    This avoids direct public bucket access requirements on frontend.
    """
    receipt = firestore_service.get_receipt(receipt_id)
    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receipt '{receipt_id}' not found.",
        )

    image_url = receipt.get("image_url")
    if not isinstance(image_url, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Receipt image URL is unavailable.",
        )

    parsed = _parse_gcs_uri(image_url)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Receipt image URL is not a valid gs:// URI.",
        )

    bucket_name, blob_name = parsed
    try:
        target_bucket = gcs_client.bucket(bucket_name)
        blob = target_bucket.blob(blob_name)
        if not blob.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receipt image object not found in storage.",
            )

        image_bytes = blob.download_as_bytes()
        media_type = blob.content_type or mimetypes.guess_type(blob_name)[0] or "application/octet-stream"
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=300"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to proxy receipt image '%s': %s", image_url, str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load receipt preview image.",
        )


# =====================================================
# 4. PUT /{receipt_id}/verify — Verify & Submit
# Reference: TDD Section 2.1 (Verify & Submit)
# =====================================================

def _flowaccount_response_ids(flowaccount_document: dict) -> dict:
    record_id = str(
        flowaccount_document.get("recordId")
        or flowaccount_document.get("record_id")
        or ""
    ).strip()
    document_id = str(
        flowaccount_document.get("documentId")
        or flowaccount_document.get("document_id")
        or ""
    ).strip()
    document_serial = str(
        flowaccount_document.get("documentSerial")
        or flowaccount_document.get("document_serial")
        or ""
    ).strip()
    return {
        "record_id": record_id,
        "document_id": document_id,
        "document_serial": document_serial,
    }


def _flowaccount_supplier_invoice_fields(supplier_invoice: dict | None) -> dict:
    data = supplier_invoice if isinstance(supplier_invoice, dict) else {}
    return {
        "id": str(data.get("id") or data.get("supplierInvoiceId") or "").strip(),
        "document_serial": str(
            data.get("documentSerial") or data.get("document_serial") or ""
        ).strip(),
        "status": data.get("supplierInvoiceStatus")
        or data.get("supplier_invoice_status"),
    }


def _assert_flowaccount_sync_allowed(current_user: dict) -> None:
    user_profile = firestore_service.get_user_profile(current_user.get("uid", "")) or {}
    normalized_role = str(user_profile.get("role", "staff")).strip().lower()
    if normalized_role not in FLOWACCOUNT_SYNC_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or executive users can sync receipts to FlowAccount.",
        )


def _verify_receipt_for_save(
    receipt_id: str,
    verified_data: ReceiptVerify,
    current_user: dict,
) -> dict:
    """
    Validate and save a receipt using the same behavior as the public verify endpoint.
    """
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
                "receipt": existing,
                "response": {
                    "receipt_id": receipt_id,
                    "status": "VERIFIED",
                    "message": "Receipt already verified. Skipped duplicate save.",
                    "bigquery_rows_inserted": 0,
                    "already_verified": True,
                },
            }

        # Allow retrying BigQuery sync for previously verified receipts.
        try:
            rows_inserted = bigquery_service.insert_verified_receipt(existing)
            existing = firestore_service.update_receipt_fields(
                receipt_id=receipt_id,
                fields={
                    "bigquery_synced": True,
                    "bigquery_rows_inserted": rows_inserted,
                    "bigquery_synced_at": datetime.utcnow().isoformat(),
                    "bigquery_sync_error": None,
                },
            )
        except Exception as exc:
            existing = firestore_service.update_receipt_fields(
                receipt_id=receipt_id,
                fields={
                    "bigquery_synced": False,
                    "bigquery_sync_error": str(exc),
                },
            )
            rows_inserted = 0

        return {
            "receipt": existing,
            "response": {
                "receipt_id": receipt_id,
                "status": "VERIFIED",
                "message": "Receipt already verified. BigQuery sync retried.",
                "bigquery_rows_inserted": rows_inserted,
                "already_verified": True,
            },
        }

    # Validate total_check matches sum of items plus signed adjustments.
    items_total = round(sum(item.amount for item in verified_data.items), 2)
    verified_adjustments = []
    for index, adjustment in enumerate(verified_data.adjustments):
        label = adjustment.label.strip()
        if not label:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each adjustment must have a label.",
            )
        if adjustment.amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each adjustment must have a positive amount.",
            )
        verified_adjustments.append(
            {
                "id": f"adj_{index + 1}",
                "type": adjustment.type.value,
                "label": label,
                "amount": round(adjustment.amount, 2),
                "is_manual_edit": False,
            }
        )

    signed_adjustments_total = _get_signed_adjustment_total(verified_adjustments)
    expected_total = round(items_total + signed_adjustments_total, 2)
    if abs(expected_total - verified_data.total_check) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Total check ({verified_data.total_check}) does not match "
                f"items plus adjustments ({expected_total})."
            ),
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
        "adjustments": verified_adjustments,
        "total_check": verified_data.total_check,
        "verified_by": current_user["uid"],
    }
    if verified_data.seller is not None:
        update_payload["seller"] = _normalize_party_payload(verified_data.seller.dict())
    if verified_data.buyer is not None:
        update_payload["buyer"] = _normalize_party_payload(verified_data.buyer.dict())

    updated = firestore_service.update_receipt_status(
        receipt_id=receipt_id,
        status="VERIFIED",
        verified_data=update_payload,
    )

    # Insert verified data into BigQuery (fact_transactions)
    # Reference: TDD Section 1.2, HLD Flow A Step 6
    try:
        rows_inserted = bigquery_service.insert_verified_receipt(updated)
        updated = firestore_service.update_receipt_fields(
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
        updated = firestore_service.update_receipt_fields(
            receipt_id=receipt_id,
            fields={
                "bigquery_synced": False,
                "bigquery_sync_error": str(exc),
            },
        )
        rows_inserted = 0

    return {
        "receipt": updated,
        "response": {
            "receipt_id": receipt_id,
            "status": "VERIFIED",
            "message": "Receipt verified and saved successfully.",
            "bigquery_rows_inserted": rows_inserted,
            "already_verified": False,
        },
    }


@router.put("/{receipt_id}/verify")
async def verify_receipt(
    receipt_id: str,
    verified_data: ReceiptVerify,
    current_user: dict = Depends(get_current_user),
):
    """
    User confirms the receipt data → Update Firestore to VERIFIED.

    The frontend sends corrected items and adjustments with total_check.
    Total must match sum(items) plus signed adjustments.
    """
    result = _verify_receipt_for_save(receipt_id, verified_data, current_user)
    return result["response"]


@router.post("/{receipt_id}/verify-and-sync-flowaccount")
async def verify_receipt_and_sync_flowaccount(
    receipt_id: str,
    verified_data: ReceiptVerifyFlowAccount,
    current_user: dict = Depends(get_current_user),
):
    """
    Verify a receipt, save OCR transactions, then create a paid FlowAccount expense
    and attach the original receipt image.
    """
    _assert_flowaccount_sync_allowed(current_user)
    try:
        flowaccount_service.ensure_configured()
    except flowaccount_service.FlowAccountConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    result = _verify_receipt_for_save(receipt_id, verified_data, current_user)
    receipt = result["receipt"]
    verify_response = result["response"]

    if receipt.get("flowaccount_synced") and not verified_data.confirm_resync:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipt already synced to FlowAccount. Confirm before creating another FlowAccount document.",
        )

    branch = firestore_service.get_branch_config(receipt.get("branch_id", ""))
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Receipt branch is missing or invalid.",
        )

    requested_payment_method = str(verified_data.payment_method or "CASH").strip().upper()
    flowaccount_payment_method = (
        "TRANSFER" if requested_payment_method in {"TRANSFER", "BANK_TRANSFER"} else requested_payment_method
    )
    selected_bank_account_id = verified_data.flowaccount_bank_account_id
    selected_transfer_bank_id = verified_data.flowaccount_transfer_bank_id
    selected_bank_account_label = str(
        verified_data.flowaccount_bank_account_label or ""
    ).strip()
    supplier_invoice_serial = str(
        verified_data.flowaccount_supplier_invoice_serial or ""
    ).strip()
    supplier_invoice_tax_form = verified_data.flowaccount_supplier_invoice_tax_form or 1

    sync_started_at = datetime.utcnow().isoformat()
    try:
        supplier_invoice_payload = flowaccount_service.build_supplier_invoice_payload(
            receipt=receipt,
            document_serial=supplier_invoice_serial,
            tax_form=supplier_invoice_tax_form,
            include_file=False,
        )
        flowaccount_reference = supplier_invoice_serial
        if isinstance(supplier_invoice_payload, dict):
            flowaccount_reference = str(
                supplier_invoice_payload.get("documentSerial") or flowaccount_reference
            ).strip()
        flowaccount_document = flowaccount_service.create_paid_expense_from_receipt(
            receipt=receipt,
            branch=branch,
            payment_method=flowaccount_payment_method,
            bank_account_id=selected_bank_account_id,
            transfer_bank_id=selected_transfer_bank_id,
            reference=flowaccount_reference,
        )
        ids = _flowaccount_response_ids(flowaccount_document)
        flowaccount_record_id = ids["record_id"] or ids["document_id"]
        if not flowaccount_record_id:
            raise flowaccount_service.FlowAccountAPIError(
                "FlowAccount response did not include a record id."
            )
    except flowaccount_service.FlowAccountConfigurationError as exc:
        firestore_service.update_receipt_fields(
            receipt_id=receipt_id,
            fields={
                "flowaccount_synced": False,
                "flowaccount_sync_error": str(exc),
                "flowaccount_last_attempt_at": sync_started_at,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except flowaccount_service.FlowAccountAPIError as exc:
        firestore_service.update_receipt_fields(
            receipt_id=receipt_id,
            fields={
                "flowaccount_synced": False,
                "flowaccount_sync_error": str(exc),
                "flowaccount_last_attempt_at": sync_started_at,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    supplier_invoice_synced = True
    supplier_invoice_error = None
    supplier_invoice_fields = {
        "id": "",
        "document_serial": supplier_invoice_serial,
        "status": None,
    }
    try:
        supplier_invoice_document = flowaccount_service.create_supplier_invoice_from_receipt(
            flowaccount_record_id=flowaccount_record_id,
            receipt=receipt,
            document_serial=supplier_invoice_serial,
            tax_form=supplier_invoice_tax_form,
            include_file=True,
        )
        supplier_invoice_fields = _flowaccount_supplier_invoice_fields(
            supplier_invoice_document
        )
        supplier_invoice_fields["document_serial"] = (
            supplier_invoice_fields["document_serial"] or supplier_invoice_serial
        )
    except (
        flowaccount_service.FlowAccountConfigurationError,
        flowaccount_service.FlowAccountAPIError,
    ) as exc:
        supplier_invoice_synced = False
        supplier_invoice_error = str(exc)

    attachment_synced = True
    attachment_error = None
    try:
        flowaccount_service.attach_receipt_file(flowaccount_record_id, receipt)
    except (
        flowaccount_service.FlowAccountConfigurationError,
        flowaccount_service.FlowAccountAPIError,
    ) as exc:
        attachment_synced = False
        attachment_error = str(exc)

    sync_count = int(receipt.get("flowaccount_sync_count") or 0) + 1
    sync_fields = {
        "flowaccount_synced": True,
        "flowaccount_synced_at": datetime.utcnow().isoformat(),
        "flowaccount_synced_by": current_user.get("uid", ""),
        "flowaccount_record_id": ids["record_id"],
        "flowaccount_document_id": ids["document_id"],
        "flowaccount_document_serial": ids["document_serial"],
        "flowaccount_attachment_synced": attachment_synced,
        "flowaccount_sync_error": attachment_error,
        "flowaccount_sync_count": sync_count,
        "flowaccount_payment_method": flowaccount_payment_method,
        "flowaccount_bank_account_id": selected_bank_account_id,
        "flowaccount_transfer_bank_id": selected_transfer_bank_id,
        "flowaccount_bank_account_label": selected_bank_account_label,
        "flowaccount_supplier_invoice_synced": supplier_invoice_synced,
        "flowaccount_supplier_invoice_error": supplier_invoice_error,
        "flowaccount_supplier_invoice_id": supplier_invoice_fields["id"],
        "flowaccount_supplier_invoice_serial": supplier_invoice_fields["document_serial"],
        "flowaccount_supplier_invoice_status": supplier_invoice_fields["status"],
        "flowaccount_supplier_invoice_tax_form": supplier_invoice_tax_form,
    }
    history = {
        **sync_fields,
        "created_at": sync_fields["flowaccount_synced_at"],
        "receipt_id": receipt_id,
        "confirm_resync": verified_data.confirm_resync,
    }
    firestore_service.record_receipt_flowaccount_sync(
        receipt_id=receipt_id,
        fields=sync_fields,
        history=history,
    )

    return {
        **verify_response,
        "flowaccount_synced": True,
        "flowaccount_record_id": ids["record_id"],
        "flowaccount_document_id": ids["document_id"],
        "flowaccount_document_serial": ids["document_serial"],
        "flowaccount_attachment_synced": attachment_synced,
        "flowaccount_attachment_error": attachment_error,
        "flowaccount_payment_method": flowaccount_payment_method,
        "flowaccount_bank_account_id": selected_bank_account_id,
        "flowaccount_bank_account_label": selected_bank_account_label,
        "flowaccount_supplier_invoice_synced": supplier_invoice_synced,
        "flowaccount_supplier_invoice_error": supplier_invoice_error,
        "flowaccount_supplier_invoice_id": supplier_invoice_fields["id"],
        "flowaccount_supplier_invoice_serial": supplier_invoice_fields["document_serial"],
        "flowaccount_supplier_invoice_status": supplier_invoice_fields["status"],
        "flowaccount_supplier_invoice_tax_form": supplier_invoice_tax_form,
    }
