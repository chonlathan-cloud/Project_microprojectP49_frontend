import asyncio
import io
import json
import logging
from typing import Any

import vertexai
from vertexai.generative_models import GenerativeModel, Part

from app.core.config import settings
from app.models.branch import get_categories_for_type
from app.models.receipt import BusinessType

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageOps = None

# --- Vertex AI Initialization ---
# Reference: LDD Section 3.1, HLD Section 2.4

vertexai.init(
    project=settings.GCP_PROJECT_ID,
    location=settings.VERTEX_AI_LOCATION,
)

logger = logging.getLogger(__name__)


model = GenerativeModel(settings.VERTEX_AI_MODEL)


def _unique_non_empty(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in unique_values:
            unique_values.append(normalized)
    return unique_values


RECEIPT_MODEL_NAMES = _unique_non_empty(
    [
        settings.VERTEX_AI_RECEIPT_MODEL,
        settings.VERTEX_AI_MODEL,
        "gemini-2.5-flash",
    ]
)
RECEIPT_MODELS = {name: GenerativeModel(name) for name in RECEIPT_MODEL_NAMES}
receipt_refine_model = RECEIPT_MODELS[RECEIPT_MODEL_NAMES[0]]

INSIGHT_MODEL_NAMES = _unique_non_empty(
    [
        settings.VERTEX_AI_INSIGHT_MODEL,
        settings.VERTEX_AI_MODEL,
        "gemini-2.5-flash",
    ]
)
INSIGHT_MODELS = {name: GenerativeModel(name) for name in INSIGHT_MODEL_NAMES}


def _extract_json_payload(response_text: str) -> dict | None:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None


async def _generate_content_with_timeout(
    target_model: GenerativeModel,
    payload: list[object],
    timeout_ms: int,
):
    timeout_seconds = max(1.0, float(timeout_ms) / 1000.0)
    return await asyncio.wait_for(
        asyncio.to_thread(target_model.generate_content, payload),
        timeout=timeout_seconds,
    )


def _should_try_next_model(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "not found",
            "does not exist",
            "invalid argument",
            "unsupported",
            "publisher model",
            "permission denied",
            "forbidden",
        )
    )


async def _generate_with_receipt_models(
    payload: list[object],
    timeout_ms: int,
) -> tuple[Any, str]:
    last_error: Exception | None = None
    for model_name in RECEIPT_MODEL_NAMES:
        target_model = RECEIPT_MODELS[model_name]
        try:
            response = await _generate_content_with_timeout(
                target_model=target_model,
                payload=payload,
                timeout_ms=timeout_ms,
            )
            return response, model_name
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            last_error = exc
            if _should_try_next_model(exc):
                logger.warning(
                    "Receipt model '%s' unavailable, trying next model: %s",
                    model_name,
                    str(exc),
                )
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("No receipt model available")


async def _generate_with_insight_models(
    payload: list[object],
    timeout_ms: int,
) -> tuple[Any, str]:
    last_error: Exception | None = None
    for model_name in INSIGHT_MODEL_NAMES:
        target_model = INSIGHT_MODELS[model_name]
        try:
            response = await _generate_content_with_timeout(
                target_model=target_model,
                payload=payload,
                timeout_ms=timeout_ms,
            )
            return response, model_name
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning(
                "Insight model '%s' timed out, trying next model",
                model_name,
            )
            continue
        except Exception as exc:
            last_error = exc
            if _should_try_next_model(exc):
                logger.warning(
                    "Insight model '%s' unavailable, trying next model: %s",
                    model_name,
                    str(exc),
                )
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("No insight model available")


def _preprocess_vision_image(
    image_bytes: bytes,
    mime_type: str,
) -> tuple[bytes, str, dict]:
    normalized_mime = (mime_type or "").lower().strip()
    if (
        not settings.VISION_PREPROCESS_ENABLED
        or not normalized_mime.startswith("image/")
        or Image is None
        or ImageOps is None
    ):
        return image_bytes, normalized_mime, {"preprocessed": False}

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")

            max_edge = max(image.size)
            if max_edge > settings.VISION_MAX_IMAGE_EDGE:
                ratio = settings.VISION_MAX_IMAGE_EDGE / float(max_edge)
                new_size = (
                    max(1, int(image.width * ratio)),
                    max(1, int(image.height * ratio)),
                )
                resampling = (
                    Image.Resampling.LANCZOS
                    if hasattr(Image, "Resampling")
                    else Image.LANCZOS
                )
                image = image.resize(new_size, resample=resampling)

            image = ImageOps.autocontrast(image)

            output = io.BytesIO()
            quality = min(95, max(50, int(settings.VISION_JPEG_QUALITY)))
            image.save(output, format="JPEG", quality=quality, optimize=True)
            processed_bytes = output.getvalue()

            return processed_bytes, "image/jpeg", {
                "preprocessed": True,
                "width": image.width,
                "height": image.height,
                "quality": quality,
            }
    except Exception as exc:
        logger.warning("Vision image preprocessing failed: %s", str(exc))
        return image_bytes, normalized_mime, {"preprocessed": False, "error": str(exc)}


async def ask_vertex_ai(text: str, business_type: str) -> dict:
    """
    Ask Vertex AI (Gemini Pro) to categorize a line item that
    could not be matched by the rule-based engine.

    Reference: LDD Section 3.1, TDD Section 3.1, BusinessLogic V2.0

    Args:
        text: The item description from OCR (e.g., "หมูบดอนามัย 1kg").
        business_type: "COFFEE" or "RESTAURANT".

    Returns:
        dict: {"id": "C1", "confidence": 0.85}
              Returns {"id": None, "confidence": 0.0} on failure.
    """
    # Build category list for the prompt
    btype = BusinessType(business_type)
    categories = get_categories_for_type(btype)
    category_list = "\n".join(
        f"- {cat.id}: {cat.name}" for cat in categories
    )

    # Construct the prompt
    # Reference: TDD Section 3.1 (prompt structure)
    prompt = f"""You are an accountant for a {business_type} business in Thailand.

Your task: Classify the following expense item into exactly ONE category.

Item: "{text}"

Available Categories:
{category_list}

Instructions:
1. Analyze the item description carefully.
2. Choose the single best-matching category ID.
3. Respond with ONLY a valid JSON object, no other text.

Output format:
{{"id": "<category_id>", "confidence": <0.0-1.0>}}

Example:
{{"id": "C1", "confidence": 0.9}}
"""

    try:
        response = model.generate_content(prompt)
        result = _extract_json_payload(response.text or "")
        if not result:
            return {"id": None, "confidence": 0.0}

        # Validate that the returned ID is in our category list
        valid_ids = {cat.id for cat in categories}
        if result.get("id") not in valid_ids:
            return {"id": None, "confidence": 0.0}

        return {
            "id": result["id"],
            "confidence": float(result.get("confidence", 0.8)),
        }

    except (json.JSONDecodeError, KeyError, ValueError):
        # AI returned unparseable response
        return {"id": None, "confidence": 0.0}
    except Exception:
        # Network / API errors
        return {"id": None, "confidence": 0.0}


async def refine_receipt_extraction(
    full_text: str,
    business_type: str,
    header_candidates: dict | None,
    line_item_candidates: list[dict] | None,
) -> dict | None:
    """
    Use one Gemini call per receipt to refine OCR output into a strict structure.
    Returns None when parsing/validation fails.
    """
    try:
        btype = BusinessType(business_type)
    except ValueError:
        return None

    categories = get_categories_for_type(btype)
    valid_category_ids = [cat.id for cat in categories]
    category_list = "\n".join(f"- {cat.id}: {cat.name}" for cat in categories)
    candidates_payload = {
        "header_candidates": header_candidates or {},
        "line_item_candidates": (line_item_candidates or [])[:40],
    }

    prompt = f"""You are a receipt extraction assistant for a {business_type} business in Thailand.
Refine noisy OCR output and return strict JSON only.

Allowed category IDs:
{category_list}

Rules:
1) Return only real purchased items.
2) Remove noise lines (tax id, member points, payment method, QR, references).
3) amount must be positive float.
4) date must be YYYY-MM-DD when possible, otherwise null.
5) merchant should be a store name, not numeric-only tax IDs.
6) category_id must be one of allowed IDs, else null.
7) If uncertain, keep item with lower confidence but still valid structure.

OCR full text:
{full_text}

OCR candidates JSON:
{json.dumps(candidates_payload, ensure_ascii=False)}

Output JSON format:
{{
  "header": {{
    "merchant": "string|null",
    "date": "YYYY-MM-DD|null",
    "total": 0.0
  }},
  "items": [
    {{
      "description": "string",
      "amount": 0.0,
      "category_id": "one of {valid_category_ids} or null",
      "confidence": 0.0
    }}
  ],
  "confidence_summary": {{
    "overall": 0.0,
    "notes": ["short reason"]
  }}
}}
"""

    try:
        response, used_model = await _generate_with_receipt_models(
            payload=[prompt],
            timeout_ms=max(9000, settings.VISION_TIMEOUT_MS),
        )
        parsed = _extract_json_payload(response.text or "")
        if not parsed:
            return None

        header = parsed.get("header")
        items = parsed.get("items")
        if not isinstance(header, dict) or not isinstance(items, list):
            return None

        normalized_items = []
        valid_ids = set(valid_category_ids)
        for item in items:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description", "")).strip()
            if not description:
                continue
            try:
                amount = float(item.get("amount", 0))
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue

            category_id = item.get("category_id")
            if category_id is not None:
                category_id = str(category_id).strip().upper()
                if category_id not in valid_ids:
                    category_id = None

            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            normalized_items.append(
                {
                    "description": description,
                    "amount": round(amount, 2),
                    "category_id": category_id,
                    "confidence": max(0.0, min(confidence, 1.0)),
                }
            )

        if not normalized_items:
            return None

        merchant = header.get("merchant")
        merchant = str(merchant).strip() if merchant else None
        date_value = header.get("date")
        date_value = str(date_value).strip() if date_value else None
        try:
            total = float(header.get("total", 0.0) or 0.0)
        except (TypeError, ValueError):
            total = 0.0

        confidence_summary = parsed.get("confidence_summary", {})
        if not isinstance(confidence_summary, dict):
            confidence_summary = {}

        return {
            "header": {
                "merchant": merchant or None,
                "date": date_value or None,
                "total": round(total, 2),
            },
            "items": normalized_items,
            "confidence_summary": confidence_summary,
            "source": "GEMINI_REFINE",
            "meta": {
                "model": used_model,
            },
        }
    except asyncio.TimeoutError:
        logger.warning("Receipt refinement timed out")
        return None
    except Exception as exc:
        logger.warning("Receipt refinement with Gemini failed: %s", str(exc))
        return None


async def extract_receipt_from_image(
    image_bytes: bytes,
    mime_type: str,
    business_type: str,
    timeout_ms: int = 9000,
    max_retry: int = 0,
) -> dict | None:
    """
    Vision-first receipt extraction: Gemini reads the uploaded image directly
    and returns structured JSON in one call.
    """
    if not image_bytes:
        return None

    normalized_mime = (mime_type or "").lower().strip()
    if not (
        normalized_mime.startswith("image/")
        or normalized_mime == "application/pdf"
    ):
        return None

    try:
        btype = BusinessType(business_type)
    except ValueError:
        return None

    categories = get_categories_for_type(btype)
    valid_category_ids = [cat.id for cat in categories]
    category_list = "\n".join(f"- {cat.id}: {cat.name}" for cat in categories)

    prompt = f"""You are an accounting OCR assistant for a {business_type} business in Thailand.
Read the receipt image and extract only reliable structured data.

Allowed category IDs:
{category_list}

Rules:
1) Keep only purchased line items with positive amount.
2) Ignore tax IDs, loyalty/member points, payment references, QR, phone numbers.
3) Preserve Thai text as-is from the receipt where possible.
4) date must be YYYY-MM-DD when confidently parsed, otherwise null.
5) merchant should be store name (not numeric-only).
6) category_id must be one of allowed IDs, otherwise null.
7) Return strict JSON only, no markdown.

Output JSON:
{{
  "header": {{
    "merchant": "string|null",
    "date": "YYYY-MM-DD|null",
    "total": 0.0
  }},
  "items": [
    {{
      "description": "string",
      "amount": 0.0,
      "category_id": "one of {valid_category_ids} or null",
      "confidence": 0.0
    }}
  ],
  "confidence_summary": {{
    "overall": 0.0,
    "notes": ["short reason"]
  }}
}}
"""

    prepared_bytes = image_bytes
    prepared_mime = normalized_mime
    preprocess_meta = {"preprocessed": False}
    if normalized_mime.startswith("image/"):
        prepared_bytes, prepared_mime, preprocess_meta = _preprocess_vision_image(
            image_bytes=image_bytes,
            mime_type=normalized_mime,
        )

    max_attempts = max(1, int(max_retry) + 1)
    image_part = Part.from_data(data=prepared_bytes, mime_type=prepared_mime)

    for attempt in range(max_attempts):
        try:
            response, used_model = await _generate_with_receipt_models(
                payload=[prompt, image_part],
                timeout_ms=timeout_ms,
            )
            parsed = _extract_json_payload(response.text or "")
            if not parsed:
                logger.warning(
                    "Gemini vision extraction returned non-JSON payload (attempt=%d/%d)",
                    attempt + 1,
                    max_attempts,
                )
                continue

            header = parsed.get("header")
            items = parsed.get("items")
            if not isinstance(header, dict) or not isinstance(items, list):
                continue

            normalized_items = []
            valid_ids = set(valid_category_ids)
            for item in items:
                if not isinstance(item, dict):
                    continue
                description = str(item.get("description", "")).strip()
                if not description:
                    continue

                try:
                    amount = float(item.get("amount", 0))
                except (TypeError, ValueError):
                    continue
                if amount <= 0:
                    continue

                category_id = item.get("category_id")
                if category_id is not None:
                    category_id = str(category_id).strip().upper()
                    if category_id not in valid_ids:
                        category_id = None

                try:
                    confidence = float(item.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0

                normalized_items.append(
                    {
                        "description": description,
                        "amount": round(amount, 2),
                        "category_id": category_id,
                        "confidence": max(0.0, min(confidence, 1.0)),
                    }
                )

            if not normalized_items:
                continue

            merchant = header.get("merchant")
            merchant = str(merchant).strip() if merchant else None
            date_value = header.get("date")
            date_value = str(date_value).strip() if date_value else None
            try:
                total = float(header.get("total", 0.0) or 0.0)
            except (TypeError, ValueError):
                total = 0.0

            confidence_summary = parsed.get("confidence_summary", {})
            if not isinstance(confidence_summary, dict):
                confidence_summary = {}

            return {
                "header": {
                    "merchant": merchant or None,
                    "date": date_value or None,
                    "total": round(total, 2),
                },
                "items": normalized_items,
                "confidence_summary": confidence_summary,
                "source": "GEMINI_VISION",
                "meta": {
                    "model": used_model,
                    "preprocess": preprocess_meta,
                },
            }
        except asyncio.TimeoutError:
            logger.warning(
                "Gemini vision extraction timed out (attempt=%d/%d timeout_ms=%d)",
                attempt + 1,
                max_attempts,
                timeout_ms,
            )
        except Exception as exc:
            logger.warning(
                "Gemini vision extraction failed (attempt=%d/%d): %s",
                attempt + 1,
                max_attempts,
                str(exc),
            )

    return None


async def generate_ai_insight(
    question: str,
    business_type: str,
    context: dict,
    timeout_ms: int | None = None,
) -> str:
    """
    Generate an executive-style answer for dashboard AI insight.
    """
    normalized_question = question.strip()
    if not normalized_question:
        return "Please provide a question for AI insight."

    effective_timeout = timeout_ms or max(9000, settings.AI_INSIGHT_TIMEOUT_MS)
    knowledge_items = []
    if isinstance(context, dict):
        kb_section = context.get("knowledge_base", {})
        if isinstance(kb_section, dict):
            raw_items = kb_section.get("items", [])
            if isinstance(raw_items, list):
                knowledge_items = [item for item in raw_items if isinstance(item, dict)]

    if knowledge_items:
        knowledge_text = "\n".join(
            (
                f"- [{item.get('topic', 'Unknown')}|{item.get('category', 'General')}] "
                f"{str(item.get('content', '')).strip()}"
            )
            for item in knowledge_items
        )
    else:
        knowledge_text = "- No playbook snippets matched this question."

    prompt = f"""Role: You are a Senior Business Analyst for a {business_type} business.
Answer using the provided data only.

Language policy:
- Default response language: Thai.
- Keep numbers and specific technical terms in English where appropriate.

Output policy:
1) Keep the answer concise and practical.
2) Do not invent metrics that are not in context.
3) If data is missing, clearly say what is unavailable.
4) End with one clear next action.
5) If playbook snippets are used, cite topic+category in text like [High Food Cost|F1].

Question:
{normalized_question}

Analytics Context JSON:
{json.dumps(context, ensure_ascii=False)}

Playbook Snippets:
{knowledge_text}
"""

    try:
        response, used_model = await _generate_with_insight_models(
            payload=[prompt],
            timeout_ms=effective_timeout,
        )
        answer = (response.text or "").strip()
        if answer:
            logger.info("AI insight generated with model=%s", used_model)
            return answer
    except Exception as exc:
        logger.warning("AI insight generation failed: %s", str(exc))

    summary = context.get("summary", {}) if isinstance(context, dict) else {}
    if isinstance(summary, dict):
        total_revenue = summary.get("total_revenue")
        total_expense = summary.get("total_expense")
        net_profit = summary.get("net_profit")
        return (
            "AI Insight ไม่พร้อมใช้งานชั่วคราว "
            f"(Revenue={total_revenue}, Expense={total_expense}, Net Profit={net_profit}). "
            "Action ที่แนะนำ: ตรวจสอบหมวดค่าใช้จ่ายสูงสุดก่อนเป็นลำดับแรก"
        )
    return "AI Insight ไม่พร้อมใช้งานชั่วคราว กรุณาลองอีกครั้ง"
