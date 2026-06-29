from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.services import firestore_service, flowaccount_service

router = APIRouter(prefix="/flowaccount", tags=["FlowAccount"])

ALLOWED_FLOWACCOUNT_ROLES = {"admin", "executive"}


def _assert_flowaccount_access(current_user: dict) -> None:
    user_profile = firestore_service.get_user_profile(current_user.get("uid", "")) or {}
    normalized_role = str(user_profile.get("role", "staff")).strip().lower()
    if normalized_role not in ALLOWED_FLOWACCOUNT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or executive users can use FlowAccount sync.",
        )


@router.get("/status")
async def get_flowaccount_status(current_user: dict = Depends(get_current_user)):
    """
    Return safe FlowAccount sync configuration status without exposing secrets.
    """
    _assert_flowaccount_access(current_user)
    payload = flowaccount_service.get_status()

    token_ok = False
    token_error = None
    if payload["enabled"] and payload["configured"]:
        try:
            flowaccount_service.get_access_token()
            token_ok = True
        except Exception as exc:
            token_error = str(exc)

    return {
        **payload,
        "token_ok": token_ok,
        "token_error": token_error,
    }


@router.get("/bank-accounts")
async def list_flowaccount_bank_accounts(current_user: dict = Depends(get_current_user)):
    """
    Return safe FlowAccount bank account options for transfer payment selection.
    """
    _assert_flowaccount_access(current_user)
    try:
        return {"bank_accounts": flowaccount_service.list_bank_accounts()}
    except flowaccount_service.FlowAccountConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except flowaccount_service.FlowAccountAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
