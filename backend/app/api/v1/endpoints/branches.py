from fastapi import APIRouter, HTTPException, status

from app.services import firestore_service

router = APIRouter(prefix="/branches", tags=["Branches"])


@router.get("")
async def get_branches():
    """
    Return branch list for frontend selectors.
    This endpoint is intentionally public read-only so the frontend can avoid
    cross-origin preflight for simple GET requests.
    """
    try:
        branches = firestore_service.list_branches()
        return {"branches": branches}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load branches: {str(exc)}",
        ) from exc
