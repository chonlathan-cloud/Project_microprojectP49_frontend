from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


# --- Enums ---
# Reference: LDD Section 2, TDD Section 1.1

class BusinessType(str, Enum):
    """Branch business type determines which expense categories apply."""
    COFFEE = "COFFEE"
    RESTAURANT = "RESTAURANT"


class ReceiptStatus(str, Enum):
    """Receipt lifecycle: DRAFT -> VERIFIED or REJECTED."""
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# --- Line Item Models ---
# Reference: LDD Section 2, TDD Section 1.1 (receipts.items)

class LineItem(BaseModel):
    """A single item extracted from a receipt (via OCR or manual entry)."""
    id: str
    description: str
    amount: float
    category_id: Optional[str] = None       # e.g., "C1", "F1"
    category_name: Optional[str] = None      # e.g., "COGS (วัตถุดิบ)"
    confidence: float = 0.0                  # AI confidence score (0.0 - 1.0)
    is_manual_edit: bool = False             # True if user overrode AI


# --- Receipt Header (from OCR) ---
# Reference: TDD Section 1.1 (receipts.header)

class ReceiptHeader(BaseModel):
    """Header data extracted by OCR from the receipt image."""
    merchant: Optional[str] = None
    date: Optional[str] = None               # YYYY-MM-DD
    total: float = 0.0


# --- Receipt Schemas ---
# Reference: LDD Section 2, TDD Section 1.1

class ReceiptBase(BaseModel):
    """Base fields shared by create and read schemas."""
    branch_id: str
    merchant_name: Optional[str] = None
    date: Optional[str] = None               # YYYY-MM-DD
    total_amount: float = 0.0
    items: List[LineItem] = []


class ReceiptCreate(ReceiptBase):
    """Schema for creating a new receipt (after OCR processing)."""
    image_url: str                           # GCS URI (gs://...)


class ReceiptInDB(ReceiptBase):
    """Schema representing a receipt stored in Firestore."""
    id: str
    user_id: str
    status: ReceiptStatus
    created_at: datetime
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None


# --- Verify & Submit Schema ---
# Reference: TDD Section 2.1 (PUT /receipts/{id}/verify)

class VerifyLineItem(BaseModel):
    """A line item submitted during verification (user-corrected)."""
    description: str
    amount: float
    category_id: str                         # Required on verify


class ReceiptVerify(BaseModel):
    """Request body for verify & submit endpoint."""
    items: List[VerifyLineItem]
    total_check: float                       # Must match sum of items
