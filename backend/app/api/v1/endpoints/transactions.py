from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.services import bigquery_service, firestore_service

router = APIRouter(prefix="/transactions", tags=["Transactions"])

ALLOWED_PRIVILEGED_ROLES = {"admin", "executive"}
ALLOWED_TRANSACTION_TYPES = {"EXPENSE", "REVENUE"}
ALLOWED_SOURCES = {"OCR", "POS_FILE"}


def _parse_date(date_value: str, field_name: str) -> str:
    try:
        return datetime.strptime(date_value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name}. Expected YYYY-MM-DD.",
        ) from exc


def _normalize_optional_upper(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip().upper()
    return normalized or None


@router.get("")
async def get_transactions(
    branch_id: str = Query(..., description="Branch ID to filter by"),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    type: str | None = Query(None, description="Optional transaction type filter"),
    category_id: str | None = Query(None, description="Optional category filter"),
    source: str | None = Query(None, description="Optional source filter"),
    limit: int = Query(100, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    sort_by: str = Query("created_at", description="Sort column"),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
    current_user: dict = Depends(get_current_user),
):
    """
    Return transaction-level rows with backend-enforced branch access.
    """
    try:
        normalized_branch_id = branch_id.strip()
        if not normalized_branch_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="branch_id is required.",
            )

        branch = firestore_service.get_branch_config(normalized_branch_id)
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid branch_id.",
            )

        user_profile = firestore_service.get_user_profile(current_user.get("uid", "")) or {}
        normalized_role = str(user_profile.get("role", "staff")).strip().lower()
        default_branch_id = str(user_profile.get("default_branch_id", "")).strip()

        if normalized_role not in ALLOWED_PRIVILEGED_ROLES:
            if not default_branch_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not assigned to a default branch.",
                )
            if default_branch_id != normalized_branch_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this branch.",
                )

        normalized_start_date = _parse_date(start_date, "start_date") if start_date else None
        normalized_end_date = _parse_date(end_date, "end_date") if end_date else None
        if normalized_start_date and normalized_end_date and normalized_start_date > normalized_end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be before or equal to end_date.",
            )

        normalized_type = _normalize_optional_upper(type)
        if normalized_type and normalized_type not in ALLOWED_TRANSACTION_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="type must be EXPENSE or REVENUE.",
            )

        normalized_source = _normalize_optional_upper(source)
        if normalized_source and normalized_source not in ALLOWED_SOURCES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source must be OCR or POS_FILE.",
            )

        normalized_category_id = _normalize_optional_upper(category_id)
        normalized_sort_by = sort_by.strip()
        if normalized_sort_by not in bigquery_service.SORTABLE_TRANSACTION_COLUMNS:
            allowed_sort_columns = ", ".join(sorted(bigquery_service.SORTABLE_TRANSACTION_COLUMNS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"sort_by must be one of: {allowed_sort_columns}",
            )

        normalized_sort_order = sort_order.strip().lower()
        if normalized_sort_order not in {"asc", "desc"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sort_order must be asc or desc.",
            )

        result = bigquery_service.list_transactions(
            branch_id=normalized_branch_id,
            start_date=normalized_start_date,
            end_date=normalized_end_date,
            transaction_type=normalized_type,
            category_id=normalized_category_id,
            source=normalized_source,
            limit=limit,
            offset=offset,
            sort_by=normalized_sort_by,
            sort_order=normalized_sort_order,
        )

        verifier_ids = [
            str(item.get("verified_by_user_id", "")).strip()
            for item in result["transactions"]
            if item.get("verified_by_user_id")
        ]
        display_names = firestore_service.get_user_display_names(verifier_ids)

        for transaction in result["transactions"]:
            verifier_id = transaction.get("verified_by_user_id")
            if verifier_id:
                transaction["verified_by_user_id"] = display_names.get(verifier_id, verifier_id)

        return result

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch transactions: {str(exc)}",
        ) from exc
