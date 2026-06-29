# Business logic SpecificationV2.0

**Project:** The 49 - Smart P&L Analysisf

**Status:** Updated for Coffee, Restaurant, & Steak House

### 1. Branch & Business Type Logic (โครงสร้างร้านค้า)

ระบบต้องแยกแยะ "ประเภทธุรกิจ" ของแต่ละสาขา เพื่อโหลด **ชุดหมวดหมู่ค่าใช้จ่าย (Expense Chart)** ให้ถูกต้อง

- **Type A: Coffee Shop** (ร้านกาแฟ)
    - ใช้โครงสร้างค่าใช้จ่าย **9 หมวด**
- **Type B: Food Business** (ร้านอาหาร & ร้านสเต็ก)
    - ใช้โครงสร้างค่าใช้จ่าย **7 หมวด** (เหมือนกันทั้งคู่)

---

### 2. Expense Categorization Logic (ตรรกะการจัดหมวดหมู่)

เมื่อ AI หรือ User ทำการระบุหมวดหมู่สินค้า ระบบจะยึดตามกฎนี้:

### **Type A: Coffee Shop (9 Categories)**

| Category ID | Category Name | Key Items / Keywords (Logic) |
| --- | --- | --- |
| **C1** | **COGS (วัตถุดิบ)** | เมล็ดกาแฟ, นม, ไซรัป, ผงชง, น้ำแข็ง, เบเกอรี่, ผลไม้, Topping |
| **C2** | **Labor (ค่าแรง)** | เงินเดือน, OT (ต้องมีลายเซ็น/เอกสารแนบ) |
| **C3** | **Rent & Place (สถานที่)** | ค่าเช่า, ค่าส่วนกลาง, ที่จอดรถ, ค่าปรับพื้นที่ |
| **C4** | **Utilities (สาธารณูปโภค)** | ไฟฟ้า, ประปา, เน็ต, โทรศัพท์ |
| **C5** | **Equip & Maint (อุปกรณ์)** | ซ่อมเครื่องชง, อะไหล่, **แก้ว/หลอด/ทิชชู่ (Consumables)** |
| **C6** | **System & Sales (ระบบ)** | ค่า POS, GP Delivery, ค่าธรรมเนียมบัตร/QR |
| **C7** | **Marketing (การตลาด)** | Ads (FB/TT), Influencer, ออกแบบ, ส่วนลดโปรโมชั่น |
| **C8** | **Admin (ทั่วไป)** | เครื่องเขียน, ทำความสะอาด, ภาษี, บัญชี |
| **C9** | **Reserve (สำรองจ่าย)** | เครื่องเสียฉุกเฉิน, ของเสีย/หมดอายุ, เงินหาย |

### **Type B: Restaurant & Steak House (7 Categories)**

| Category ID | Category Name | Key Items / Keywords (Logic) |
| --- | --- | --- |
| **F1** | **Main Ingredients (วัตถุดิบหลัก)** | **(ต้นทุนใหญ่สุด)** เนื้อสัตว์, ผัก, ไข่, ข้าว, เส้น, เครื่องปรุง, กะทิ |
| **F2** | **Labor (ค่าแรง)** | เงินเดือน, OT (ต้องมีลายเซ็น/เอกสารแนบ) |
| **F3** | **Fuel (เชื้อเพลิง)** | แก๊สหุงต้ม, ถ่าน |
| **F4** | **Containers (ภาชนะ)** | กล่องโฟม, ถุงแกง, ช้อนส้อม, หนังยาง, ทิชชู่ |
| **F5** | **Water & Ice (น้ำ)** | น้ำดื่ม, น้ำแข็ง, น้ำอัดลม |
| **F6** | **Daily Waste (ของเสีย)** | **(Critical)** อาหารเหลือทิ้ง, วัตถุดิบเน่า, ตักเกิน/หก (ต้องบันทึกทุกวัน) |
| **F7** | **Daily Misc (เบ็ดเตล็ด)** | ค่าเช่ารายวัน, ที่จอดรถ, ค่าขยะ, ทำความสะอาด |

---

### 3. Revenue Logic (ตรรกะรายรับ)

ข้อมูลรายรับจะมาจากไฟล์ **POS (Excel/CSV)** เท่านั้น โดยมี Logic การจัดการดังนี้:

1. **Data Source:** ไฟล์จาก POS ของแต่ละสาขา
2. **Mapping Key:** จับคู่ด้วย `Branch ID` และ `Date`
3. **Payment Methods:**
    - **Cash (เงินสด):** นับเป็นเงินสดในมือ
    - **Transfer (เงินโอน):** รวม KPlus, SCB, Credit Card (เงินเข้าบัญชี)
4. **Menu Item Analysis:** (Optional for Phase 1) เก็บชื่อเมนูที่ขายได้ เพื่อให้ AI วิเคราะห์ "Menu Mix" (เมนูขายดี vs เมนูกำไรเยอะ)

---

### 4. Operational Flow Logic (ลำดับการทำงาน)

**Step 1: Ingestion (นำเข้า)**

- User เลือกสาขา -> อัปโหลดรูปใบเสร็จ
- **System Logic:** ตรวจสอบว่าสาขานั้นเป็น Type A หรือ B เพื่อเตรียม AI Model ให้ถูกตัว

**Step 2: AI Processing (ประมวลผล)**

- OCR อ่านข้อความ
- **Auto-Tagging:** AI พยายาม Map สินค้าเข้าหมวดหมู่
    - *Example:* เจอคำว่า "หมูบด" และสาขาเป็น "ร้านสเต็ก" -> Auto-select **F1 (Main Ingredients)**
    - *Example:* เจอคำว่า "แก้วพลาสติก" และสาขาเป็น "ร้านกาแฟ" -> Auto-select **C5 (Equip & Maint)**

**Step 3: Human Validation (ตรวจสอบ)**

- แสดงหน้าจอเปรียบเทียบ (รูป vs ข้อมูล)
- User (คุณหมิว) มีอำนาจสูงสุดในการแก้ไขหมวดหมู่
- กด **Submit** -> ข้อมูลเปลี่ยนสถานะเป็น `Verified` (พร้อมคำนวณ)

**Step 4: Calculation (คำนวณ)**

- **Daily P&L:** `Revenue (POS) - Verified Expenses`
- **Food Cost %:** `(Category F1 + F6) / Revenue` (สำหรับร้านอาหาร)

---

### 5. AI Analysis Logic (สมองกลผู้บริหาร)

AI จะทำงานบนข้อมูลที่ `Verified` แล้วเท่านั้น:

- **Context Awareness:** AI ต้องรู้ว่ากำลังวิเคราะห์ร้านประเภทไหน
    - *ถ้าเป็นร้านอาหาร:* AI จะโฟกัสที่ **F1 (วัตถุดิบ)** และ **F6 (Waste)** เป็นพิเศษ เพราะเป็นจุดรั่วไหลหลัก
    - *ถ้าเป็นร้านกาแฟ:* AI จะโฟกัสที่ **C1 (COGS)** และ **C2 (Labor)**
- **Anomaly Detection:** แจ้งเตือนเมื่อตัวเลขผิดปกติ (เช่น ค่าแก๊ส F3 สูงผิดปกติเทียบกับยอดขาย)