from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.services import bigquery_service

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
        summary = bigquery_service.get_expense_summary(
            branch_id=branch_id,
            start_date=start_date,
            end_date=end_date,
        )
        return summary

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch analytics: {str(e)}",
        )
