from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.services import firestore_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """
    Return the authenticated user's app profile from Firestore.

    The frontend uses this endpoint as the role source so UI permissions match
    backend authorization checks, even when client Firestore rules differ.
    """
    uid = str(current_user.get("uid", "")).strip()
    profile = firestore_service.get_user_profile(uid) or {}

    email = str(profile.get("email") or current_user.get("email") or "").strip()
    display_name = str(
        profile.get("display_name")
        or current_user.get("name")
        or current_user.get("email")
        or "Authenticated User"
    ).strip()
    role = str(profile.get("role") or "staff").strip().lower()
    default_branch_id = str(profile.get("default_branch_id") or "").strip()

    return {
        "uid": uid,
        "email": email,
        "display_name": display_name,
        "role": role,
        "default_branch_id": default_branch_id,
        "profile_exists": bool(profile),
    }
