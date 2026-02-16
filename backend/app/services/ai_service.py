import json
import vertexai
from vertexai.generative_models import GenerativeModel

from app.core.config import settings
from app.models.branch import get_categories_for_type
from app.models.receipt import BusinessType

# --- Vertex AI Initialization ---
# Reference: LDD Section 3.1, HLD Section 2.4

vertexai.init(
    project=settings.GCP_PROJECT_ID,
    location=settings.GCP_LOCATION,
)

model = GenerativeModel(settings.VERTEX_AI_MODEL)


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
        response_text = response.text.strip()

        # Clean up response — strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first line (```json) and last line (```)
            response_text = "\n".join(lines[1:-1]).strip()

        result = json.loads(response_text)

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
