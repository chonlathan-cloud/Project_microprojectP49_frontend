from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_user
from app.models.branch import get_categories_for_type
from app.models.receipt import BusinessType
from app.services import ai_service, bigquery_service, firestore_service, knowledge_base

router = APIRouter(prefix="/ai", tags=["AI"])


class AiChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    context_branch: str = Field(..., min_length=1)
    start_date: str = Field(..., min_length=10, max_length=10)
    end_date: str = Field(..., min_length=10, max_length=10)
    category_id: str | None = Field(default=None, max_length=10)


class AiChatResponse(BaseModel):
    answer: str
    citations: list[str] = []
    kb_used: bool = False
    fallback_mode: str = "bigquery_only"


@router.post("/chat", response_model=AiChatResponse)
async def ai_chat(
    payload: AiChatRequest,
    _current_user: dict = Depends(get_current_user),
):
    """
    Generate AI insight text for dashboard Q&A.
    """
    try:
        try:
            start = datetime.strptime(payload.start_date, "%Y-%m-%d").date()
            end = datetime.strptime(payload.end_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Expected YYYY-MM-DD.",
            ) from exc

        if start > end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be before or equal to end_date.",
            )

        branch = firestore_service.get_branch_config(payload.context_branch)
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid context_branch.",
            )

        branch_type_raw = str(branch.get("type", BusinessType.RESTAURANT.value)).upper()
        try:
            branch_type = BusinessType(branch_type_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported branch type: {branch_type_raw}",
            ) from exc

        normalized_category_id = (
            payload.category_id.strip().upper() if payload.category_id else None
        )
        if normalized_category_id:
            allowed_category_ids = {cat.id for cat in get_categories_for_type(branch_type)}
            if normalized_category_id not in allowed_category_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"category_id '{normalized_category_id}' is not valid for "
                        f"{branch_type.value} branch."
                    ),
                )

        summary: dict = {}
        analytics_error: str | None = None
        try:
            summary = bigquery_service.get_expense_summary(
                branch_id=payload.context_branch,
                start_date=payload.start_date,
                end_date=payload.end_date,
                category_id=normalized_category_id,
            )
        except Exception as exc:  # Keep AI chat available even if analytics data fails.
            analytics_error = str(exc)

        retrieval_query = payload.question
        if normalized_category_id:
            retrieval_query = f"{payload.question}\nCategory: {normalized_category_id}"

        kb_items: list[dict] = []
        kb_error: str | None = None
        try:
            kb_items = knowledge_base.retrieve_relevant_advice(
                query=retrieval_query,
                k=settings.KNOWLEDGE_BASE_TOP_K,
                category_id=normalized_category_id,
            )
        except Exception as exc:
            kb_error = str(exc)
        if not kb_items and kb_error is None:
            kb_status = knowledge_base.get_knowledge_base_status()
            if not kb_status.get("ready"):
                kb_error = kb_status.get("last_error")

        citations = [
            f"{item.get('topic', 'Unknown')} ({item.get('category', 'General')})"
            for item in kb_items
        ]

        context = {
            "branch": {
                "id": payload.context_branch,
                "name": branch.get("name"),
                "type": branch_type.value,
            },
            "date_range": {
                "start_date": payload.start_date,
                "end_date": payload.end_date,
            },
            "category_id": normalized_category_id,
            "summary": summary,
            "analytics_error": analytics_error,
            "knowledge_base": {
                "items": kb_items,
                "error": kb_error,
            },
        }

        answer = await ai_service.generate_ai_insight(
            question=payload.question,
            business_type=branch_type.value,
            context=context,
        )
        return AiChatResponse(
            answer=answer,
            citations=citations,
            kb_used=bool(kb_items),
            fallback_mode="hybrid" if kb_items else "bigquery_only",
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate AI insight: {str(exc)}",
        ) from exc
