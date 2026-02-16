from app.models.receipt import BusinessType
from app.models.branch import (
    COFFEE_CATEGORIES,
    RESTAURANT_CATEGORIES,
    get_categories_for_type,
)
from app.services.ai_service import ask_vertex_ai

# --- Hybrid Categorization Engine ---
# Reference: LLD Section 3.1, TDD Section 3.1, BusinessLogic V2.0
#
# Two-layer approach:
#   Layer 1 (Rule-based): Fast keyword matching — zero cost, instant.
#   Layer 2 (AI Fallback): Vertex AI Gemini — smart but costs per call.

# Minimum confidence threshold for AI results
AI_CONFIDENCE_THRESHOLD = 0.5


async def categorize_line_item(text: str, business_type: str) -> dict:
    """
    Categorize a single OCR-extracted line item into an expense category.

    Reference: LLD Section 3.1 (Categorization Engine)

    Args:
        text: Item description from OCR (e.g., "นมสด Meiji 2L").
        business_type: "COFFEE" or "RESTAURANT".

    Returns:
        dict: {
            "category_id": str or None,
            "category_name": str or None,
            "confidence": float,
            "source": "RULE" | "AI" | "NONE"
        }
    """
    # Normalize text for matching
    normalized = text.strip().lower()

    # --- Layer 1: Rule-based Keyword Matching ---
    # Uses category lists from app/models/branch.py (no duplication)
    btype = BusinessType(business_type)
    categories = get_categories_for_type(btype)

    for category in categories:
        for keyword in category.keywords:
            if keyword.lower() in normalized:
                return {
                    "category_id": category.id,
                    "category_name": category.name,
                    "confidence": 1.0,
                    "source": "RULE",
                }

    # --- Layer 2: AI Fallback (Vertex AI / Gemini) ---
    try:
        ai_result = await ask_vertex_ai(text, business_type)

        if ai_result.get("id") and ai_result.get("confidence", 0) >= AI_CONFIDENCE_THRESHOLD:
            # Look up the full category name
            cat_name = None
            for category in categories:
                if category.id == ai_result["id"]:
                    cat_name = category.name
                    break

            return {
                "category_id": ai_result["id"],
                "category_name": cat_name,
                "confidence": ai_result["confidence"],
                "source": "AI",
            }
    except Exception:
        pass  # Fall through to uncategorized

    # --- Fallback: Uncategorized ---
    return {
        "category_id": None,
        "category_name": "Uncategorized",
        "confidence": 0.0,
        "source": "NONE",
    }
