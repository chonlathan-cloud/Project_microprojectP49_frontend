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


class AdjustmentType(str, Enum):
    """Adjustment types captured outside normal purchased items."""
    DISCOUNT = "discount"
    SERVICE_CHARGE = "service_charge"
    ROUNDING = "rounding"
    OTHER = "other"


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


class AdjustmentItem(BaseModel):
    """A receipt-level adjustment such as discount or service charge."""
    id: str
    type: AdjustmentType
    label: str
    amount: float
    is_manual_edit: bool = False


# --- Receipt Header (from OCR) ---
# Reference: TDD Section 1.1 (receipts.header)

class ReceiptHeader(BaseModel):
    """Header data extracted by OCR from the receipt image."""
    merchant: Optional[str] = None
    date: Optional[str] = None               # YYYY-MM-DD
    total: float = 0.0
    vat: float = 0.0


# --- Receipt Schemas ---
# Reference: LDD Section 2, TDD Section 1.1

class ReceiptBase(BaseModel):
    """Base fields shared by create and read schemas."""
    branch_id: str
    merchant_name: Optional[str] = None
    date: Optional[str] = None               # YYYY-MM-DD
    total_amount: float = 0.0
    items: List[LineItem] = Field(default_factory=list)
    adjustments: List[AdjustmentItem] = Field(default_factory=list)


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


class VerifyAdjustment(BaseModel):
    """An adjustment submitted during verification."""
    type: AdjustmentType
    label: str
    amount: float


class ReceiptVerify(BaseModel):
    """Request body for verify & submit endpoint."""
    items: List[VerifyLineItem]
    adjustments: List[VerifyAdjustment] = Field(default_factory=list)
    total_check: float                       # Must match items + signed adjustments
