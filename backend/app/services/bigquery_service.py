from google.cloud import bigquery
from datetime import datetime

from app.core.config import settings

# --- BigQuery Client ---
# Reference: TDD Section 1.2, LDD Section 3

bq_client = bigquery.Client(project=settings.GCP_PROJECT_ID)

# Fully qualified table ID
FACT_TRANSACTIONS_TABLE = f"{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET}.fact_transactions"


def insert_verified_receipt(receipt: dict) -> int:
    """
    Insert verified receipt items into BigQuery fact_transactions table.
    One row per line item.

    Reference: TDD Section 1.2 (BigQuery Schema)

    Args:
        receipt: The full receipt dict from Firestore, including:
            - id, branch_id, header.date, items (list of dicts)

    Returns:
        int: Number of rows inserted.

    Schema (fact_transactions):
        transaction_id  STRING   - Unique ID (receipt_id + item index)
        branch_id       STRING   - Branch reference
        date            DATE     - Transaction date
        type            STRING   - 'EXPENSE' or 'REVENUE'
        category_id     STRING   - Category code (C1-C9, F1-F7)
        category_name   STRING   - Category name (denormalized)
        item_name       STRING   - Item description
        amount          NUMERIC  - Amount
        payment_method  STRING   - 'CASH', 'TRANSFER'
        source          STRING   - 'OCR', 'POS_FILE'
        created_at      TIMESTAMP
    """
    receipt_id = receipt.get("id", "unknown")
    branch_id = receipt.get("branch_id", "")
    receipt_date = receipt.get("header", {}).get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    uploaded_by_user_id = receipt.get("user_id", "")
    verified_by_user_id = receipt.get("verified_by", "")
    items = receipt.get("items", [])

    if not items:
        return 0

    # Build rows for BigQuery
    rows_to_insert = []
    for idx, item in enumerate(items):
        row = {
            "transaction_id": f"{receipt_id}_item_{idx + 1}",
            "branch_id": branch_id,
            "date": receipt_date,
            "type": "EXPENSE",
            "category_id": item.get("category_id", ""),
            "category_name": item.get("category_name", ""),
            "item_name": item.get("description", ""),
            "amount": float(item.get("amount", 0.0)),
            "payment_method": "CASH",  # Default; POS data will have actual values
            "source": "OCR",
            "uploaded_by_user_id": uploaded_by_user_id,
            "verified_by_user_id": verified_by_user_id,
            "created_at": datetime.utcnow().isoformat(),
        }
        rows_to_insert.append(row)

    # Insert rows using the streaming API
    errors = bq_client.insert_rows_json(FACT_TRANSACTIONS_TABLE, rows_to_insert)

    if errors:
        raise Exception(f"BigQuery insert errors: {errors}")

    return len(rows_to_insert)


def get_expense_summary(
    branch_id: str,
    start_date: str,
    end_date: str,
    category_id: str | None = None,
) -> dict:
    """
    Fetch aggregated expense data from BigQuery for the dashboard.

    Reference: TDD Section 2.3 (GET /analytics/summary)

    Args:
        branch_id: Branch to filter by.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        category_id: Optional category filter. If present, REVENUE remains unfiltered
            and EXPENSE is narrowed to this category.

    Returns:
        dict: {
            "total_revenue": float,
            "total_expense": float,
            "net_profit": float,
            "expense_by_category": [{"category_id": ..., "category_name": ..., "total": ...}]
        }
    """
    # Parameterized query to prevent SQL injection
    query = """
    SELECT
        type,
        category_id,
        category_name,
        SUM(amount) AS total_amount
    FROM `{table}`
    WHERE branch_id = @branch_id
      AND date BETWEEN @start_date AND @end_date
      AND (
        @category_id IS NULL
        OR type = 'REVENUE'
        OR category_id = @category_id
      )
    GROUP BY type, category_id, category_name
    ORDER BY total_amount DESC
    """.format(table=FACT_TRANSACTIONS_TABLE)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("branch_id", "STRING", branch_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            bigquery.ScalarQueryParameter("category_id", "STRING", category_id),
        ]
    )

    query_job = bq_client.query(query, job_config=job_config)
    results = query_job.result()

    total_expense = 0.0
    total_revenue = 0.0
    expense_by_category = []

    for row in results:
        amount = float(row.total_amount or 0)
        if row.type == "EXPENSE":
            total_expense += amount
            expense_by_category.append({
                "category_id": row.category_id,
                "category_name": row.category_name,
                "total": amount,
            })
        elif row.type == "REVENUE":
            total_revenue += amount

    net_profit = total_revenue - total_expense

    # Food Cost % (for restaurant: F1 + F6 / Revenue)
    food_cost_categories = {"F1", "F6", "C1"}
    food_cost = sum(
        cat["total"] for cat in expense_by_category
        if cat["category_id"] in food_cost_categories
    )
    food_cost_percent = (food_cost / total_revenue * 100) if total_revenue > 0 else 0.0

    # Top expense category
    top_category = expense_by_category[0] if expense_by_category else None

    return {
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "net_profit": net_profit,
        "food_cost_percent": round(food_cost_percent, 1),
        "top_expense_category": (
            f"{top_category['category_id']} ({top_category['category_name']})"
            if top_category else None
        ),
        "expense_by_category": expense_by_category,
    }
