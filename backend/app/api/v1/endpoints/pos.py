import io
import re
import uuid
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import get_current_user
from app.services import bigquery_service

# Reference: TDD Section 2.2 (POS Integration)

router = APIRouter(prefix="/pos", tags=["POS"])

REQUIRED_STANDARD_COLUMNS = ("date", "amount", "payment_method")
COLUMN_ALIASES = {
    "date": {
        "date",
        "วันที่",
        "วันที่ขาย",
        "transactiondate",
        "salesdate",
        "datetime",
    },
    "amount": {
        "amount",
        "total",
        "ยอดขาย",
        "ยอดรวม",
        "ยอดขายสุทธิ",
        "saleamount",
        "netsales",
    },
    "payment_method": {
        "paymentmethod",
        "payment_type",
        "payment",
        "paymenttype",
        "วิธีชำระ",
        "ช่องทางชำระ",
    },
}


def _normalize_column_key(column_name: str) -> str:
    text = str(column_name).strip().lower()
    # Keep only latin/digits/thai chars, drop spaces and symbols (e.g. "(Net Sales)")
    return re.sub(r"[^a-z0-9\u0E00-\u0E7F]+", "", text)


def _read_pos_file(file_content: bytes, filename: str) -> pd.DataFrame:
    if not filename or "." not in filename:
        raise ValueError("Unsupported file format. Please upload CSV or Excel.")

    extension = filename.rsplit(".", 1)[-1].lower()
    file_buffer = io.BytesIO(file_content)

    try:
        if extension == "csv":
            return pd.read_csv(file_buffer)
        if extension in {"xls", "xlsx"}:
            return pd.read_excel(file_buffer)
    except Exception as exc:
        raise ValueError(
            "Unable to read POS file. Please upload a valid CSV or Excel file."
        ) from exc

    raise ValueError("Unsupported file format. Please upload CSV or Excel.")


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    normalized_aliases = {
        standard_name: [_normalize_column_key(alias) for alias in aliases]
        for standard_name, aliases in COLUMN_ALIASES.items()
    }

    for column in df.columns:
        normalized_key = _normalize_column_key(column)
        if not normalized_key:
            continue

        matched_standard = None
        for standard_name, aliases in normalized_aliases.items():
            if standard_name in rename_map.values():
                continue
            if any(
                normalized_key == alias
                or normalized_key.startswith(alias)
                or alias in normalized_key
                for alias in aliases
                if alias
            ):
                matched_standard = standard_name
                break

        if matched_standard:
            rename_map[column] = matched_standard

    standardized_df = df.rename(columns=rename_map)
    missing = [col for col in REQUIRED_STANDARD_COLUMNS if col not in standardized_df]
    if missing:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing)
            + ". Required columns are date, amount, payment_method."
        )

    return standardized_df


def _map_payment_method(value: object) -> str:
    method = str(value).strip().lower()
    return "CASH" if method in {"cash", "เงินสด"} else "TRANSFER"


@router.post("/upload")
async def upload_pos_file(
    branch_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload POS file (CSV/Excel), normalize fields, validate, and insert REVENUE rows.
    """
    try:
        file_content = await file.read()
        if not file_content:
            raise ValueError("Uploaded file is empty.")

        df = _read_pos_file(file_content, file.filename or "")
        if df.empty:
            raise ValueError("Uploaded POS file has no data rows.")

        df = _standardize_columns(df)

        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        if df["amount"].isna().any():
            raise ValueError("Column 'amount' must contain valid numeric values.")
        if (df["amount"] <= 0).any():
            raise ValueError("Column 'amount' must contain only positive values.")

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if df["date"].isna().any():
            raise ValueError("Column 'date' contains invalid date values.")

        df["payment_method"] = df["payment_method"].apply(_map_payment_method)

        inserted_rows = 0
        for _, row in df.iterrows():
            payload = {
                "transaction_id": f"pos_{branch_id}_{uuid.uuid4().hex}",
                "branch_id": branch_id,
                "date": row["date"].date().isoformat(),
                "type": "REVENUE",
                "category_id": "",
                "category_name": "",
                "item_name": "POS Revenue",
                "amount": float(row["amount"]),
                "payment_method": row["payment_method"],
                "source": "POS_FILE",
                "uploaded_by_user_id": current_user.get("uid", ""),
                "verified_by_user_id": "",
                "created_at": datetime.utcnow().isoformat(),
            }
            errors = bigquery_service.bq_client.insert_rows_json(
                bigquery_service.FACT_TRANSACTIONS_TABLE,
                [payload],
            )
            if errors:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"BigQuery insert failed: {errors}",
                )
            inserted_rows += 1

        return {
            "status": "success",
            "branch_id": branch_id,
            "rows_inserted": inserted_rows,
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process POS file: {str(exc)}",
        ) from exc
