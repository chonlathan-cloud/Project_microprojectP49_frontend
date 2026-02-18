from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.services import firestore_service

router = APIRouter(prefix="/branches", tags=["Branches"])


@router.get("")
async def get_branches(
    _current_user: dict = Depends(get_current_user),
):
    """
    Return branch list for frontend selectors.
    """
    try:
        branches = firestore_service.list_branches()
        return {"branches": branches}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load branches: {str(exc)}",
        ) from exc
