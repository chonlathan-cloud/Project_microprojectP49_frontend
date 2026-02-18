from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.models.branch import get_categories_for_type
from app.models.receipt import BusinessType
from app.services import bigquery_service, firestore_service

# Reference: TDD Section 2.3 (Analytics & AI)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# =====================================================
# GET /summary — Dashboard Summary
# Reference: TDD Section 2.3 (Get Dashboard Summary)
# =====================================================

@router.get("/summary")
async def get_dashboard_summary(
    branch_id: str = Query(..., description="Branch ID to filter by"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    category_id: str | None = Query(
        None,
        description="Optional category filter by branch type (COFFEE: C1-C9, RESTAURANT: F1-F7)",
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Fetch aggregated P&L summary for the dashboard.

    Returns:
        - total_revenue: Sum of all REVENUE transactions
        - total_expense: Sum of all EXPENSE transactions
        - net_profit: Revenue - Expense
        - food_cost_percent: (F1 + F6) / Revenue * 100
        - top_expense_category: Highest expense category
        - expense_by_category: Breakdown by category
    """
    try:
        # Validate date format and ordering.
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
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

        # Validate branch and category compatibility.
        branch = firestore_service.get_branch_config(branch_id)
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid branch_id.",
            )

        branch_type_raw = str(branch.get("type", BusinessType.RESTAURANT.value)).upper()
        try:
            branch_type = BusinessType(branch_type_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported branch type: {branch_type_raw}",
            ) from exc

        allowed_category_ids = {cat.id for cat in get_categories_for_type(branch_type)}
        normalized_category_id = category_id.strip().upper() if category_id else None
        if normalized_category_id and normalized_category_id not in allowed_category_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"category_id '{normalized_category_id}' is not valid for "
                    f"{branch_type.value} branch."
                ),
            )

        summary = bigquery_service.get_expense_summary(
            branch_id=branch_id,
            start_date=start_date,
            end_date=end_date,
            category_id=normalized_category_id,
        )
        return summary

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch analytics: {str(e)}",
        )
