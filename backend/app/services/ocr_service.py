import io
import logging
import re
import time
from datetime import datetime

from google.cloud import documentai_v1 as documentai

from app.core.config import settings

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageOps = None

# --- Document AI Client ---
# Reference: LDD Section 3.2, HLD Section 2.4

logger = logging.getLogger(__name__)

client = documentai.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{settings.DOCAI_LOCATION}-documentai.googleapis.com"}
)

# Full resource name for the Invoice Processor
PROCESSOR_NAME = client.processor_path(
    settings.GCP_PROJECT_ID,
    settings.DOCAI_LOCATION,
    settings.DOCAI_PROCESSOR_ID,
)

LINE_ITEM_AMOUNT_PATTERN = re.compile(
    r"^(?P<description>.+?)\s+(?P<amount>\d[\d,]*(?:\.\d{1,2})?)(?:\s*[A-Za-z])?$"
)
DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)
DATE_REGEX = re.compile(
    r"(?<!\d)(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})(?!\d)"
)
TOTAL_LINE_KEYWORDS = ("ยอดรวม", "รวมสุทธิ", "total", "grand total", "net total")
NOISE_KEYWORDS = (
    "tax id",
    "tax invoice",
    "receipt",
    "vat",
    "member",
    "สมาชิก",
    "promptpay",
    "promptp",
    "online card",
    "onlinecard",
    "credit card",
    "debit card",
    "qr",
    "tel",
    "โทร",
    "คะแนน",
    "promotion",
    "promo",
    "rid",
)


def _normalize_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _preprocess_image(file_content: bytes, mime_type: str) -> tuple[bytes, str, dict]:
    """
    Normalize image orientation/size for faster OCR and better recognition quality.
    Falls back to the original bytes on any preprocessing failure.
    """
    if (
        not settings.OCR_PREPROCESS_ENABLED
        or not mime_type.startswith("image/")
        or Image is None
        or ImageOps is None
    ):
        return file_content, mime_type, {"preprocessed": False}

    try:
        with Image.open(io.BytesIO(file_content)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")

            max_edge = max(image.size)
            if max_edge > settings.OCR_MAX_IMAGE_EDGE:
                ratio = settings.OCR_MAX_IMAGE_EDGE / float(max_edge)
                new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                resampling = (
                    Image.Resampling.LANCZOS
                    if hasattr(Image, "Resampling")
                    else Image.LANCZOS
                )
                image = image.resize(new_size, resample=resampling)

            image = ImageOps.autocontrast(image)

            output = io.BytesIO()
            quality = min(95, max(50, settings.OCR_JPEG_QUALITY))
            image.save(output, format="JPEG", quality=quality, optimize=True)

            processed_bytes = output.getvalue()
            return processed_bytes, "image/jpeg", {
                "preprocessed": True,
                "width": image.width,
                "height": image.height,
                "quality": quality,
            }
    except Exception as exc:
        logger.warning("OCR image preprocessing failed: %s", str(exc))
        return file_content, mime_type, {"preprocessed": False, "error": str(exc)}


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None

    cleaned = str(value).strip().replace(",", "")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = f"{parts[0]}.{''.join(parts[1:])}"

    if cleaned in {"", ".", "-", "-."}:
        return None

    try:
        amount = float(cleaned)
    except ValueError:
        return None

    return amount if amount > 0 else None


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None

    candidate = _normalize_text(value)
    for date_format in DATE_PATTERNS:
        try:
            return datetime.strptime(candidate, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _is_noise_text(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True

    lowered = normalized.lower()
    lowered_compact = lowered.replace("-", "")
    if any(keyword in lowered or keyword in lowered_compact for keyword in NOISE_KEYWORDS):
        return True

    # Ignore mostly-numeric lines such as IDs, phone numbers and transaction refs.
    digits = sum(ch.isdigit() for ch in normalized)
    letters = sum(ch.isalpha() for ch in normalized)
    length = len(normalized)
    if letters == 0 and digits >= max(6, int(length * 0.5)):
        return True
    if re.fullmatch(r"[\d\W_]+", normalized):
        return True

    return False


def _extract_line_items_from_text(text: str) -> list[dict]:
    line_items: list[dict] = []
    seen_keys: set[tuple[str, float]] = set()

    for raw_line in text.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            continue

        match = LINE_ITEM_AMOUNT_PATTERN.match(line)
        if not match:
            continue

        description = _normalize_text(match.group("description"))
        amount = _parse_amount(match.group("amount"))
        if amount is None:
            continue

        if _is_noise_text(description):
            continue
        if any(keyword in description.lower() for keyword in TOTAL_LINE_KEYWORDS):
            continue

        item_key = (description.lower(), round(amount, 2))
        if item_key in seen_keys:
            continue
        seen_keys.add(item_key)

        line_items.append(
            {
                "description": description,
                "amount": round(amount, 2),
                "ocr_confidence": 0.65,
            }
        )

    return line_items


def _build_line_item_candidates(entities: list[dict], full_text: str) -> list[dict]:
    candidates: list[dict] = []
    seen_keys: set[tuple[str, float]] = set()

    for item in _extract_line_items_from_text(full_text):
        key = (item["description"].lower(), round(float(item["amount"]), 2))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(
            {
                "description": item["description"],
                "amount": float(item["amount"]),
                "confidence": float(item.get("ocr_confidence", 0.0)),
                "source": "text_line",
            }
        )

    for entity in entities:
        entity_type = str(entity.get("type", "")).lower()
        mention_text = _normalize_text(entity.get("mention_text", ""))
        if not mention_text:
            continue
        if "line_item" not in entity_type and "item" not in entity_type:
            continue

        match = LINE_ITEM_AMOUNT_PATTERN.match(mention_text)
        if not match:
            continue
        description = _normalize_text(match.group("description"))
        amount = _parse_amount(match.group("amount"))
        if not description or amount is None:
            continue
        if _is_noise_text(description):
            continue

        key = (description.lower(), round(amount, 2))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(
            {
                "description": description,
                "amount": round(amount, 2),
                "confidence": float(entity.get("confidence", 0.0)),
                "source": "entity",
            }
        )

    return candidates


def _build_header_candidates(entities: list[dict], full_text: str, line_items: list[dict]) -> dict:
    merchants: list[dict] = []
    dates: list[dict] = []
    totals: list[dict] = []

    for entity in entities:
        entity_type = str(entity.get("type", "")).lower()
        mention_text = _normalize_text(entity.get("mention_text", ""))
        if not mention_text:
            continue

        confidence = float(entity.get("confidence", 0.0))

        if any(keyword in entity_type for keyword in ("supplier", "vendor", "merchant")):
            merchants.append(
                {"value": mention_text, "confidence": confidence, "source": f"entity:{entity_type}"}
            )
        if "date" in entity_type:
            normalized_date = _normalize_date(entity.get("normalized_value") or mention_text)
            if normalized_date:
                dates.append(
                    {"value": normalized_date, "confidence": confidence, "source": f"entity:{entity_type}"}
                )
        if "total" in entity_type and "subtotal" not in entity_type:
            parsed_total = _parse_amount(entity.get("normalized_value") or mention_text)
            if parsed_total is not None:
                totals.append(
                    {"value": round(parsed_total, 2), "confidence": confidence, "source": f"entity:{entity_type}"}
                )

    date_match = DATE_REGEX.search(full_text)
    if date_match:
        normalized_date = _normalize_date(date_match.group(1))
        if normalized_date:
            dates.append({"value": normalized_date, "confidence": 0.55, "source": "text_regex"})

    for raw_line in full_text.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            continue
        lowered = line.lower()
        if any(keyword in lowered for keyword in TOTAL_LINE_KEYWORDS):
            match = LINE_ITEM_AMOUNT_PATTERN.match(line)
            if not match:
                continue
            parsed_total = _parse_amount(match.group("amount"))
            if parsed_total is not None:
                totals.append({"value": round(parsed_total, 2), "confidence": 0.65, "source": "text_total_line"})

    if line_items:
        totals.append(
            {
                "value": round(sum(item.get("amount", 0.0) for item in line_items), 2),
                "confidence": 0.5,
                "source": "sum_line_items",
            }
        )

    return {
        "merchant_candidates": merchants,
        "date_candidates": dates,
        "total_candidates": totals,
    }


def _extract_header(entities: list[dict], full_text: str, line_items: list[dict]) -> tuple[dict, dict]:
    header_candidates = _build_header_candidates(entities, full_text, line_items)

    merchant: str | None = None
    date_value: str | None = None
    total_value: float | None = None

    if header_candidates["merchant_candidates"]:
        merchant = sorted(
            header_candidates["merchant_candidates"],
            key=lambda item: item.get("confidence", 0.0),
            reverse=True,
        )[0].get("value")

    if header_candidates["date_candidates"]:
        date_value = sorted(
            header_candidates["date_candidates"],
            key=lambda item: item.get("confidence", 0.0),
            reverse=True,
        )[0].get("value")

    if header_candidates["total_candidates"]:
        total_value = sorted(
            header_candidates["total_candidates"],
            key=lambda item: item.get("confidence", 0.0),
            reverse=True,
        )[0].get("value")

    header = {
        "merchant": merchant,
        "date": date_value,
        "total": float(total_value or 0.0),
    }
    return header, header_candidates


def process_invoice(file_content: bytes, mime_type: str) -> dict:
    """
    Send a receipt/invoice image to Google Document AI for OCR processing.

    Reference: LDD Section 3.2, TDD Section 2.1 (Upload Receipt flow)

    The processor used is the pre-trained "Invoice Processor" which
    handles Thai-language receipts out of the box (HLD Section 2.4).

    Args:
        file_content: Raw bytes of the uploaded image/PDF.
        mime_type: MIME type string (e.g., "image/jpeg", "application/pdf").

    Returns:
        dict: Parsed document data containing:
            - "text": Full extracted text
            - "entities": List of extracted fields (date, total, supplier, etc.)
            - "pages": Page-level layout information
    """
    process_started = time.perf_counter()
    normalized_content, normalized_mime_type, preprocess_meta = _preprocess_image(
        file_content=file_content,
        mime_type=mime_type,
    )
    preprocess_ms = round((time.perf_counter() - process_started) * 1000, 2)

    raw_document = documentai.RawDocument(
        content=normalized_content,
        mime_type=normalized_mime_type,
    )

    ocr_started = time.perf_counter()
    request = documentai.ProcessRequest(
        name=PROCESSOR_NAME,
        raw_document=raw_document,
    )

    result = client.process_document(request=request)
    ocr_ms = round((time.perf_counter() - ocr_started) * 1000, 2)
    document = result.document

    # --- Extract structured data from the Document AI response ---

    # 1. Full text
    full_text = document.text

    # 2. Entities (header fields: merchant, date, total, etc.)
    entities = []
    for entity in document.entities:
        entity_data = {
            "type": entity.type_,
            "mention_text": entity.mention_text,
            "confidence": entity.confidence,
        }
        # Include normalized value if available (e.g., date, money)
        if entity.normalized_value:
            entity_data["normalized_value"] = entity.normalized_value.text
        entities.append(entity_data)

    # 3. Page-level info (optional, for bounding box overlay)
    pages = []
    for page in document.pages:
        page_data = {
            "page_number": page.page_number,
            "width": page.dimension.width if page.dimension else None,
            "height": page.dimension.height if page.dimension else None,
        }
        pages.append(page_data)

    line_items = _extract_line_items_from_text(full_text)
    line_item_candidates = _build_line_item_candidates(entities, full_text)
    header, header_candidates = _extract_header(entities, full_text, line_items)
    total_ms = round((time.perf_counter() - process_started) * 1000, 2)

    return {
        "text": full_text,
        "entities": entities,
        "pages": pages,
        "line_items": line_items,
        "line_item_candidates": line_item_candidates,
        "header": header,
        "header_candidates": header_candidates,
        "meta": {
            "preprocess": preprocess_meta,
            "timings_ms": {
                "preprocess": preprocess_ms,
                "ocr": ocr_ms,
                "total": total_ms,
            },
        },
    }
