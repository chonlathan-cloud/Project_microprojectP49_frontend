# 🏗️ Technical Design Document (TDD)

**Project:** The 491 - Smart P&L Analysis

**Version:** 1.0

**Tech Stack:** Python (FastAPI), Google Cloud Platform (Cloud Run, Firestore, BigQuery, Vertex AI)

---

## 1. Database Schema Design (การออกแบบฐานข้อมูล)

เราใช้ระบบ **Hybrid Database**:

1. **Firestore (NoSQL):** สำหรับจัดการ State ของ Web App (Draft, User, Config)
2. **BigQuery (SQL):** สำหรับเก็บข้อมูลที่ Verify แล้วเพื่อทำ Analytics

### 1.1 Firestore Schema (Operational DB)

**Collection: `branches`**

เก็บข้อมูลสาขาและประเภทธุรกิจ (เพื่อเลือก Logic การลงบัญชี)

```json
{
  "id": "branch_001",
  "name": "Siam Square One",
  "type": "COFFEE", // Enum: "COFFEE", "RESTAURANT"
  "created_at": "2023-10-01T10:00:00Z"
}
```

**Collection: `receipts`**

เก็บข้อมูลใบเสร็จทุกสถานะ (Draft -> Verified)

```json
{
  "id": "rcpt_xyz123",
  "branch_id": "branch_001",
  "user_id": "user_mew",
  "status": "DRAFT", // Enum: "DRAFT", "VERIFIED", "REJECTED"
  "image_url": "https://storage.googleapis.com/...",
  "upload_timestamp": "2023-10-25T08:30:00Z",

  // ข้อมูล Header ที่ OCR อ่านได้
  "header": {
    "merchant": "Makro",
    "date": "2023-10-24",
    "total": 1500.00
  },

  // รายการสินค้า (Line Items)
  "items": [
    {
      "id": "item_1",
      "description": "นมสด Meiji 2L",
      "amount": 95.00,
      "category_id": "C1", // Auto-mapped by AI
      "category_name": "COGS (วัตถุดิบ)",
      "confidence": 0.98,
      "is_manual_edit": false
    },
    {
      "id": "item_2",
      "description": "ค่าซ่อมแอร์",
      "amount": 500.00,
      "category_id": "C5",
      "category_name": "Equip & Maint",
      "confidence": 0.85
    }
  ],

  "verified_at": null,
  "verified_by": null
}
```

### 1.2 BigQuery Schema (Analytical DB)

**Table: `fact_transactions`**

ตารางหลักสำหรับเก็บ Transaction ทั้งหมด (Expense & Revenue) ที่ผ่านการ Verify แล้ว

| Field Name | Type | Description |
| --- | --- | --- |
| `transaction_id` | STRING | Unique ID (Ref from Firestore/POS) |
| `branch_id` | STRING | รหัสสาขา |
| `date` | DATE | วันที่เกิดรายการ |
| `type` | STRING | 'EXPENSE' or 'REVENUE' |
| `category_id` | STRING | รหัสหมวดหมู่ (C1-C9, F1-F7) |
| `category_name` | STRING | ชื่อหมวดหมู่ (Denormalized for speed) |
| `item_name` | STRING | ชื่อรายการสินค้า / เมนู |
| `amount` | NUMERIC | ยอดเงิน |
| `payment_method` | STRING | 'CASH', 'TRANSFER' |
| `source` | STRING | 'OCR', 'POS_FILE' |
| `created_at` | TIMESTAMP | เวลาที่บันทึกเข้าระบบ |

---

## 2. API Specification (FastAPI Endpoints)

เราจะใช้มาตรฐาน **RESTful API** โดย Response ทั้งหมดจะเป็น JSON

### 2.1 Receipt Management (จัดการใบเสร็จ)

**1. Upload Receipt**

- **Endpoint:** `POST /api/v1/receipts/upload`
- **Description:** รับไฟล์ภาพ -> Upload GCS -> Trigger OCR -> Auto-Categorize -> Save Draft
- **Request:** `Multipart/Form-Data` (file, branch_id)
- **Response:**
    
    ```json
    {
      "receipt_id": "rcpt_xyz123",
      "status": "DRAFT",
      "items": [...] // ข้อมูลที่ AI แกะได้เบื้องต้น
    }
    ```
    

**2. Get Receipt Detail**

- **Endpoint:** `GET /api/v1/receipts/{receipt_id}`
- **Description:** ดึงข้อมูล Draft มาแสดงบนหน้า Web (Side-by-Side View)
- **Response:** JSON Object ของ Receipt นั้นๆ

**3. Verify & Submit (Critical)**

- **Endpoint:** `PUT /api/v1/receipts/{receipt_id}/verify`
- **Description:** User ยืนยันความถูกต้อง (หลังจากแก้ไขแล้ว) -> Update Firestore -> Insert BigQuery
- **Request Body:**
    
    ```json
    {
      "items": [
        {"description": "นมสด", "amount": 95, "category_id": "C1"},
        {"description": "ไม้กวาด", "amount": 120, "category_id": "C8"} // User แก้จาก C1 เป็น C8
      ],
      "total_check": 215.00 // ยอดรวมต้องตรงกัน
    }
    ```
    

### 2.2 POS Integration (นำเข้ารายรับ)

**4. Upload POS File**

- **Endpoint:** `POST /api/v1/pos/upload`
- **Description:** รับไฟล์ Excel/CSV -> Clean Data -> Insert BigQuery
- **Request:** `Multipart/Form-Data` (file, branch_id)

### 2.3 Analytics & AI (Dashboard)

**5. Get Dashboard Summary**

- **Endpoint:** `GET /api/v1/analytics/summary`
- **Query Params:** `branch_id`, `start_date`, `end_date`
- **Response:**
    
    ```json
    {
      "total_revenue": 50000,
      "total_expense": 30000,
      "net_profit": 20000,
      "food_cost_percent": 35.5,
      "top_expense_category": "F1 (Raw Material)"
    }
    ```
    

**6. Ask AI Insight**

- **Endpoint:** `POST /api/v1/ai/chat`
- **Request:** `{"question": "ทำไมกำไรลดลง?", "context_branch": "branch_001"}`
- **Response:** `{"answer": "จากการวิเคราะห์ พบว่า Food Cost สูงขึ้น 10% เนื่องจาก..."}`

---

## 3. Component Logic Details (รายละเอียดการทำงานภายใน)

### 3.1 Auto-Categorization Logic (The Brain)

Function นี้จะทำงานทันทีหลังจาก OCR อ่านข้อความได้

```python
def categorize_item(item_text, branch_type):
    # 1. Pre-processing
    text = clean_text(item_text) # ลบอักขระพิเศษ

    # 2. Rule-based Matching (Fast & Cheap)
    # โหลด Keyword จาก Config (Firestore)
    rules = load_rules(branch_type)
    for category, keywords in rules.items():
        if any(k in text for k in keywords):
            return category # เจอ Keyword จบเลย

    # 3. AI Fallback (Smart but Costly)
    # ถ้าไม่เจอ Keyword ให้ถาม Vertex AI
    prompt = f"""
    Role: Accountant for {branch_type}
    Item: "{text}"
    Task: Assign Category ID from list {get_category_list(branch_type)}
    Output: JSON {{"id": "..."}}
    """
    response = vertex_ai.generate(prompt)
    return response.json()['id']
```

### 3.2 POS Data Normalization

Logic การจัดการไฟล์ POS ที่ Format ไม่แน่นอน

```python
def process_pos_file(file, branch_id):
    df = pd.read_excel(file)

    # 1. Standardize Columns (Fuzzy Match)
    # หา Column ที่ชื่อคล้าย "Date", "วันที่", "Time" -> Rename เป็น "date"
    # หา Column ที่ชื่อคล้าย "Total", "Amount", "ยอดขาย" -> Rename เป็น "amount"

    # 2. Map Payment Methods
    df['payment_method'] = df['payment_type'].apply(lambda x:
        'CASH' if x in ['Cash', 'เงินสด'] else 'TRANSFER'
    )

    # 3. Validate
    if df['amount'].sum() < 0:
        raise ValueError("ยอดขายติดลบไม่ได้")

    return df
```

---

## 4. Infrastructure & Security

### 4.1 Google Cloud Services Setup

- **Cloud Run:**
    - Service Name: `the491-api`
    - CPU/Memory: 1 CPU, 512MB (Auto-scale 0-10 instances)
    - Env Vars: `GCP_PROJECT_ID`, `FIRESTORE_DB`, `BIGQUERY_DATASET`
- **Service Accounts:**
    - `the491-backend-sa`: ให้สิทธิ์ `Firestore User`, `BigQuery Data Editor`, `Storage Object Admin`, `Vertex AI User`.

### 4.2 Security Measures

1. **Authentication:** Frontend ส่ง `Authorization: Bearer <Firebase_ID_Token>` มาทุก Request.
2. **Input Validation:** ใช้ **Pydantic** ใน FastAPI เพื่อตรวจสอบ Data Type ก่อนประมวลผล (ป้องกัน Injection).
3. **CORS:** อนุญาตเฉพาะ Domain ของ Web App เราเท่านั้น.

---

## 5. Implementation Roadmap (แผนการลงมือทำ)

นี่คือลำดับการเขียน Code ใน Phase ถัดไป (LLD & Coding):

1. **Setup Project:** สร้าง Git Repo, ลง FastAPI, เชื่อมต่อ Firebase Admin SDK.
2. **Core Module:** เขียน API Upload และเชื่อมต่อ Google Document AI.
3. **Logic Module:** เขียน Function `categorize_item` (เริ่มจาก Rule-based ก่อน แล้วค่อยเติม Vertex AI).
4. **Database Module:** เขียน Function บันทึก Draft ลง Firestore.
5. **Frontend Integration:** ทำหน้า Web ง่ายๆ เพื่อทดสอบ Upload และดูผล JSON.