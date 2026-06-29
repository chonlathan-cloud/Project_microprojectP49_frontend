# 🛠️ Low-Level Design (LLD) Document

**Project:** The 491 - Smart P&L Analysis

**Component:** Backend Service (Python FastAPI)

**Repository Structure:** Monorepo

---

## 1. Project Directory Structure (โครงสร้างไฟล์)

เราจะเริ่มจากฝั่ง **Backend** ก่อน เพราะเป็นหัวใจหลักของระบบครับ

```
project-the491/
├── backend/
│   ├── Dockerfile                  # สำหรับ Build Cloud Run Image
│   ├── requirements.txt            # Dependencies (fastapi, google-cloud-*, pandas, pydantic)
│   ├── .env                        # Environment Variables (Local Dev)
│   └── app/
│       ├── __init__.py
│       ├── main.py                 # Entry Point (FastAPI App)
│       ├── core/                   # Core Config & Security
│       │   ├── config.py           # Load Env Vars
│       │   └── security.py         # Firebase Auth Verification
│       ├── models/                 # Data Models (Pydantic Schemas)
│       │   ├── receipt.py          # Receipt & LineItem Models
│       │   └── branch.py           # Branch & Category Models
│       ├── api/                    # API Route Handlers
│       │   ├── v1/
│       │   │   ├── endpoints/
│       │   │   │   ├── receipts.py # Upload, Get, Verify
│       │   │   │   ├── pos.py      # POS Upload
│       │   │   │   └── analytics.py# Dashboard & AI Chat
│       │   │   └── api.py          # Router Aggregator
│       └── services/               # Business Logic (The Brain)
│           ├── ocr_service.py      # Google Document AI Wrapper
│           ├── ai_service.py       # Vertex AI (Gemini) Wrapper
│           ├── categorization.py   # Hybrid Logic (Rules + AI)
│           ├── firestore_service.py# DB Operations
│           └── bigquery_service.py # Analytics Data Operations
├── frontend/                       # (Next.js Structure - To be defined later)
└── infrastructure/                 # Terraform / Cloud Build
```

---

## 2. Data Models (Pydantic Schemas)

ไฟล์: `backend/app/models/receipt.py`

กำหนดหน้าตาของข้อมูลที่จะรับส่งผ่าน API และเก็บลง DB

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class BusinessType(str, Enum):
    COFFEE = "COFFEE"
    RESTAURANT = "RESTAURANT"

class ReceiptStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"

class LineItem(BaseModel):
    id: str
    description: str
    amount: float
    category_id: Optional[str] = None  # e.g., "C1", "F1"
    category_name: Optional[str] = None
    confidence: float = 0.0
    is_manual_edit: bool = False

class ReceiptBase(BaseModel):
    branch_id: str
    merchant_name: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD
    total_amount: float = 0.0
    items: List[LineItem] = []

class ReceiptCreate(ReceiptBase):
    image_url: str  # GCS URI

class ReceiptInDB(ReceiptBase):
    id: str
    user_id: str
    status: ReceiptStatus
    created_at: datetime
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
```

---

## 3. Core Business Logic (Services)

ส่วนนี้คือ "สมอง" ของระบบครับ

### 3.1 Categorization Engine (Hybrid Logic)

ไฟล์: `backend/app/services/categorization.py`

```python
from app.services.ai_service import ask_vertex_ai

# Hardcoded Rules for Speed & Cost Saving
COFFEE_KEYWORDS = {
    "C1": ["เมล็ด", "นม", "ไซรัป", "น้ำแข็ง", "แก้ว"],
    "C4": ["ไฟฟ้า", "ประปา", "internet", "wifi"],
    # ... เพิ่มตาม Business Logic V2
}

RESTAURANT_KEYWORDS = {
    "F1": ["หมู", "ไก่", "ผัก", "ข้าว", "ไข่"],
    "F3": ["แก๊ส", "ถ่าน"],
    # ... เพิ่มตาม Business Logic V2
}

async def categorize_line_item(text: str, business_type: str) -> dict:
    """
    Returns: {"category_id": str, "confidence": float, "source": str}
    """
    # 1. Select Rule Set
    rules = COFFEE_KEYWORDS if business_type == "COFFEE" else RESTAURANT_KEYWORDS

    # 2. Rule-based Matching (Layer 1)
    for cat_id, keywords in rules.items():
        for kw in keywords:
            if kw in text:
                return {"category_id": cat_id, "confidence": 1.0, "source": "RULE"}

    # 3. AI Fallback (Layer 2) - Only if no rule matches
    # เรียก Vertex AI (Gemini)
    ai_result = await ask_vertex_ai(text, business_type)
    return {
        "category_id": ai_result.get("id"),
        "confidence": ai_result.get("confidence", 0.8),
        "source": "AI"
    }
```

### 3.2 OCR Service (Document AI)

ไฟล์: `backend/app/services/ocr_service.py`

```python
from google.cloud import documentai_v1 as documentai

def process_invoice(file_content: bytes, mime_type: str):
    client = documentai.DocumentProcessorServiceClient()
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    raw_document = documentai.RawDocument(content=file_content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)

    result = client.process_document(request=request)
    document = result.document

    # Extract Entities (Date, Total, Supplier)
    # Extract Line Items (Loop through entities)
    return parsed_data_json
```

---

## 4. API Implementation (Endpoints)

ไฟล์: `backend/app/api/v1/endpoints/receipts.py`

```python
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.services import ocr_service, categorization, firestore_service
from app.models.receipt import ReceiptInDB

router = APIRouter()

@router.post("/upload", response_model=ReceiptInDB)
async def upload_receipt(
    branch_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user) # Auth Check
):
    # 1. Upload to GCS
    gcs_uri = await upload_to_gcs(file)

    # 2. Process OCR
    ocr_data = ocr_service.process_invoice(await file.read(), file.content_type)

    # 3. Get Branch Info (to know if Coffee or Restaurant)
    branch_info = firestore_service.get_branch(branch_id)

    # 4. Auto-Categorize Items
    enriched_items = []
    for item in ocr_data['items']:
        cat_result = await categorization.categorize_line_item(
            item['description'],
            branch_info['type']
        )
        item.update(cat_result)
        enriched_items.append(item)

    # 5. Save Draft to Firestore
    receipt_doc = {
        "branch_id": branch_id,
        "user_id": current_user['uid'],
        "status": "DRAFT",
        "image_url": gcs_uri,
        "items": enriched_items,
        # ... other fields
    }
    saved_receipt = firestore_service.create_receipt(receipt_doc)

    return saved_receipt

@router.put("/{receipt_id}/verify")
async def verify_receipt(receipt_id: str, verified_data: ReceiptUpdate):
    # 1. Update Firestore status to VERIFIED
    # 2. Insert into BigQuery (fact_expenses)
    # 3. Return Success
    pass
```

---

## 5. Configuration & Environment Variables

ไฟล์: `backend/.env` (ห้าม Commit ขึ้น Git)

```
# Google Cloud Config
GCP_PROJECT_ID=project-the491
GCP_LOCATION=asia-southeast1
GCP_STORAGE_BUCKET=the491-receipts

# Document AI
DOCAI_PROCESSOR_ID=xxxxxxxxxxxx

# Vertex AI
VERTEX_AI_MODEL=gemini-pro

# Database
FIRESTORE_DB=(default)
BIGQUERY_DATASET=the491_analytics

# Security
FIREBASE_CREDENTIALS_PATH=./firebase-adminsdk.json
```

---

## 6. Next Steps (Implementation Plan)

ตอนนี้เรามี LLD ที่พร้อมสำหรับการ Coding แล้วครับ

**แผนการทำงาน (Action Plan):**

1. **Initialize Repo:** สร้าง Folder Structure ตามข้อ 1.
2. **Setup GCP:**
    - สร้าง Project ใน GCP Console.
    - เปิดใช้งาน API: Document AI, Vertex AI, Firestore, BigQuery, Cloud Run.
    - สร้าง Service Account และโหลด Key JSON มา.
3. **Backend Coding (Sprint 1):**
    - เขียน `models/` และ `core/config.py`.
    - เขียน `ocr_service.py` ให้เชื่อมต่อ Document AI ได้จริง.
    - เขียน API `/upload` ให้รับไฟล์และคืนค่า JSON ได้.