## 2. Component Deep Dive (เจาะลึกส่วนประกอบ)

### 2.1 Frontend (Web Dashboard)

- **Technology:** Next.js (React) + Tailwind CSS
- **Key Features:**
    - **Upload Zone:** รองรับ Drag & Drop ไฟล์รูป/PDF และเลือกสาขา (Branch Selector).
    - **Validation Interface (Side-by-Side):** หน้าจอแบ่งครึ่ง ซ้ายแสดงรูปใบเสร็จ ขวาแสดง Form ข้อมูลที่ AI ดึงมา (Editable).
    - **Dashboard:** กราฟแสดง P&L, Food Cost %, และกล่อง Chat สำหรับคุยกับ AI.

### 2.2 Backend API (The Brain)

- **Technology:** Python FastAPI (รันบน Cloud Run)
- **Modules:**
    - **Ingestion Service:** จัดการไฟล์ Upload และส่งไป OCR.
    - **Categorization Engine:** หัวใจสำคัญของ Logic
        - *Input:* ข้อความจาก OCR + Branch Type (Coffee/Restaurant).
        - *Process:* เช็ค Keyword (Rule-based) -> ถ้าไม่เจอ -> ถาม Vertex AI (Semantic Match).
        - *Output:* Category ID (e.g., `F1`, `C5`).
    - **POS Handler:** ใช้ Library `Pandas` อ่านไฟล์ Excel/CSV, แปลงชื่อ Column, และจัดการเรื่องวันที่ (Date Parsing).

### 2.3 Database Strategy (Hybrid)

เราใช้ Database 2 ตัวเพื่อจุดประสงค์ที่ต่างกัน:

- **A. Cloud Firestore (NoSQL):** *สำหรับ Operational Data (Real-time)*
    - เก็บข้อมูลที่ "กำลังทำงาน" (Drafts) และข้อมูล User.
    - โครงสร้างยืดหยุ่น รองรับ JSON จาก OCR ที่แต่ละใบเสร็จหน้าตาไม่เหมือนกัน.
    - **Collections:** `users`, `branches`, `receipts` (เก็บ status: draft/verified).
- **B. BigQuery (Data Warehouse):** *สำหรับ Analytical Data (Reporting)*
    - เก็บข้อมูลที่ "Verified แล้ว" และข้อมูล POS.
    - รองรับ SQL ซับซ้อนเพื่อคำนวณ P&L ข้ามเดือน/ปี.
    - **Tables:** `fact_expenses`, `fact_revenues`, `dim_branch`, `dim_category`.

### 2.4 AI Services

- **Document AI:** ใช้ Model **"Invoice Processor"** (Pre-trained) ซึ่งเก่งเรื่องใบเสร็จภาษาไทยอยู่แล้ว ไม่ต้องเทรนเองใหม่.
- **Vertex AI (Gemini Pro):**
    - Role 1: ช่วย Categorize สินค้าที่ชื่อแปลกๆ.
    - Role 2: เป็น Business Analyst ตอบคำถามผู้บริหาร โดยอ่านข้อมูลสรุปจาก BigQuery.

---

## 3. Data Flow Specifications (รายละเอียดการไหลของข้อมูล)

### Flow A: Receipt Processing (Human-in-the-loop)

กระบวนการเปลี่ยนรูปภาพเป็นข้อมูลบัญชีที่ถูกต้อง

1. **Upload:** User อัปโหลดรูป -> Backend บันทึกลง GCS -> ได้ `gs://...` URI.
2. **Extraction:** Backend ส่ง URI ให้ Document AI -> ได้ JSON (Text, Bounding Box).
3. **Auto-Mapping:**
    - Backend ดึง `Branch Type` (เช่น Restaurant).
    - Loop ผ่านรายการสินค้า (Line Items).
    - เทียบ Keyword: "หมู" -> `F1`.
    - ถ้าไม่เจอ Keyword -> เรียก Vertex AI: "หมูบดอนามัย คือหมวดไหนใน [F1-F7]?" -> ได้ `F1`.
4. **Drafting:** บันทึก JSON ลง Firestore (`status: "DRAFT"`).
5. **Verification:** User เปิดหน้าเว็บ -> แก้ไขตัวเลข/หมวดหมู่ -> กด **Submit**.
6. **Finalization:**
    - Update Firestore (`status: "VERIFIED"`).
    - **Trigger:** Insert ข้อมูลลง BigQuery `fact_expenses` ทันที.

### Flow B: POS Integration

กระบวนการนำเข้ารายรับ

1. **Upload:** User อัปโหลด Excel -> Backend รับไฟล์.
2. **Normalization (Pandas):**
    - Rename Columns: `วันที่` -> `date`, `ยอดขาย` -> `amount`.
    - Map Payment: `เงินสด` -> `CASH`, `โอน` -> `TRANSFER`.
3. **Load:** Insert ลง BigQuery `fact_revenues` (Partition by Date).

### Flow C: AI Executive Insight

กระบวนการวิเคราะห์ข้อมูล

1. **Question:** ผู้บริหารพิมพ์ "ทำไม Food Cost เดือนนี้สูง?"
2. **Data Fetching:** Backend รัน SQL ดึงข้อมูลสรุปเดือนนี้เทียบกับเดือนก่อน จาก BigQuery.
3. **Prompting:** Backend สร้าง Prompt:
    - *Context:* "Food Cost เดือนนี้ 45% (เป้า 35%), หมวด F6 (Waste) สูงขึ้น 20%."
    - *Instruction:* "วิเคราะห์สาเหตุและแนะนำวิธีแก้ปัญหา."
4. **Answer:** Vertex AI ตอบกลับ -> แสดงผลบน Dashboard.

---

## 4. Security & Scalability

- **Authentication:** ใช้ **Firebase Authentication** (Email/Password) ง่ายและปลอดภัย เชื่อมต่อกับ Frontend ได้เลย.
- **Authorization:** ตรวจสอบสิทธิ์ในระดับ API (เช่น User สาขา A ห้ามดูข้อมูลสาขา B).
- **Scalability:** **Cloud Run** จะ Scale จำนวน Instance ขึ้นลงอัตโนมัติตามปริมาณการใช้งาน (ถ้าไม่มีคนใช้ = 0 บาท).

---

## 5. Key Decision Points (จุดตัดสินใจสำคัญ)

1. **ทำไมต้องมี Firestore? ทำไมไม่ลง BigQuery เลย?**
    - *เหตุผล:* BigQuery ไม่เหมาะกับการอ่าน/เขียนทีละรายการ (Transaction) และแก้ไขข้อมูลบ่อยๆ (Edit Draft). Firestore เร็วกว่ามากสำหรับการทำหน้า Web App ที่ต้องตอบสนองทันที.
2. **ทำไมใช้ Python FastAPI?**
    - *เหตุผล:* เป็นภาษาที่ดีที่สุดสำหรับงาน AI/Data (Pandas, Google Cloud Libraries) และ FastAPI ทำงานได้รวดเร็ว (Asynchronous) เหมาะกับการรอผลจาก AI.

graph TD
    %% --- Client Layer ---
    subgraph Client_Layer ["1. Client Layer (Frontend)"]
        Web["Web Dashboard\n(Next.js / React)"]
        Mobile[Mobile Web View]
    end

    %% --- Application Layer ---
    subgraph App_Layer ["2. Application Layer (Cloud Run)"]
        LB[Load Balancer]
        API["Core API Service\n(Python FastAPI)"]
        
        subgraph Logic_Modules ["Internal Logic Modules"]
            Auth[Auth Service]
            Ingest[Ingestion Service]
            CatEngine["Categorization Engine\n(Rule-based + AI)"]
            Analytics[Analytics Service]
        end
    end

    %% --- AI Layer ---
    subgraph AI_Layer ["3. AI Intelligence Layer"]
        DocAI["Google Document AI\n(OCR Invoice Processor)"]
        Vertex["Vertex AI (Gemini Pro)\n(Insight & Reasoning)"]
    end

    %% --- Data Layer ---
    subgraph Data_Layer ["4. Data Layer"]
        GCS["Cloud Storage (GCS)\n(Raw Images/PDFs)"]
        Firestore["Firestore (NoSQL)\n(App State, Drafts, User Data)"]
        BQ["(BigQuery Data Warehouse)\n(Analytics, P&L, History)"]
    end

    %% --- External ---
    POS["POS System Export\n(Excel/CSV)"]

    %% --- Connections ---
    Web -->|HTTPS / JWT| LB
    LB --> API
    API --> Auth
    
    %% Upload Flow
    User((Khun Mew)) -->|Upload Receipt| Web
    Web -->|File Stream| API
    API -->|Save File| GCS
    API -->|Trigger OCR| DocAI
    DocAI -->|Return JSON| API
    
    %% Logic Flow
    API -->|Map Categories| CatEngine
    CatEngine -->|Read Rules| Firestore
    API -->|Save Draft| Firestore
    
    %% Validation Flow
    User -->|Verify & Edit| Web
    Web -->|Submit| API
    API -->|Update Status| Firestore
    API -->|Stream Verified Data| BQ
    
    %% POS Flow
    User -->|Upload POS File| Web
    Web -->|Send CSV| API
    API -->|Clean & Normalize| Ingest
    Ingest -->|Insert Rows| BQ

    %% Analytics Flow
    Exec((Executive)) -->|View Dashboard| Web
    Web -->|Fetch Aggregates| API
    API -->|Run SQL| BQ
    
    %% AI Insight Flow
    Exec -->|Ask Question| Web
    Web -->|Send Prompt| API
    API -->|Fetch Context| BQ
    API -->|Generate Answer| Vertex
    Vertex -->|Return Insight| API