# SPA 49 — Business Logic Specification

| รายการ | รายละเอียด |
| --- | --- |
| Product | SPA 49 Booking & Operations |
| Document | Business Logic |
| Version | 2.0 |
| Status | Approved business baseline |
| Last updated | 2 กันยายน 2026 |
| Initial branch scope | 1 สาขา |
| Timezone / Currency | Asia/Bangkok / THB |

## 1. วัตถุประสงค์ของเอกสาร

เอกสารนี้กำหนดกฎทางธุรกิจของระบบจองบริการ SPA 49 ระยะที่ 1 ตั้งแต่ลูกค้าเริ่มจองผ่าน LINE Official Account (LINE OA) หรือ Public Website, การกันห้อง/เตียง, การตรวจสอบโดยผู้ใช้งาน Admin Web หรือสมาชิกใน LINE Admin Group, การยืนยันลูกค้า ไปจนถึงการจบการให้บริการ

เอกสารนี้เป็น Business Source of Truth สำหรับจัดทำเอกสารลำดับถัดไป:

1. High-Level Design (HLD)
2. Technical Design (TDD)
3. Low-Level Design (LLD)

เอกสารนี้อธิบายว่า “ระบบต้องทำอะไรและมีกฎอะไร” โดยยังไม่กำหนด architecture, technology stack, API contract หรือ database schema

## 2. ลำดับความสำคัญของแหล่งข้อมูล

เมื่อข้อมูลขัดแย้งกัน ให้ใช้ลำดับความสำคัญดังนี้:

1. Requirement และคำยืนยันล่าสุดจาก Product Owner
2. Business Logic ฉบับนี้
3. HLD, TDD และ LLD ฉบับที่อนุมัติใน repository
4. เอกสาร UX/UI ภายใน `SPA/Document/DESING/`
5. Google Stitch projects ซึ่งใช้เป็น UX/UI reference แบบ read-only เท่านั้น

Google Stitch ที่อนุญาตให้ใช้อ้างอิงสำหรับ SPA มีเพียง:

- `SPA-Customer-Views`
- `SPA-Admin-Views`

ชื่อบริการ ราคา เนื้อหา สถานะ และ flow ที่ปรากฏใน Stitch ไม่ถือเป็น Business Requirement จนกว่าจะได้รับการยืนยันในเอกสารนี้หรือเอกสาร Requirement ที่ใหม่กว่า ข้อยกเว้นคือ Initial Service Catalog ในหัวข้อ 7.1 ซึ่ง Product Owner ยืนยันให้อ้างอิง `SPA-Customer-Views` แล้ว

## 3. เป้าหมายทางธุรกิจ

- ให้ลูกค้าจองคิวได้ด้วยตนเองจาก Rich Menu ของ Customer LINE OA หรือ Public Website
- ให้ลูกค้าที่ไม่มี LINE สามารถจองแบบ Guest ได้โดยใช้ชื่อเล่นและเบอร์โทรศัพท์ โดยไม่บังคับสมัครสมาชิกหรือ OTP
- ลดการตอบแชตเพื่อสอบถามเวลาว่างและลดความผิดพลาดในการรับคิว
- ป้องกันการจองเกิน Capacity ของห้อง/เตียง
- ให้ผู้ใช้ `ADMIN`/`STAFF` หรือสมาชิกใน LINE Admin Group ตรวจสอบและยืนยันคำขอได้รวดเร็ว
- ให้ร้านเป็นผู้จัดสรรหมอนวด โดยลูกค้าไม่ต้องเลือกหมอนวด
- ส่งรายละเอียดสุขภาพที่ลูกค้าแจ้งให้ Registered Admin LINE Group เพื่อเตรียมบริการ โดยจำกัดสมาชิกกลุ่มเฉพาะผู้ปฏิบัติงานที่มีหน้าที่และข้อผูกพันด้านการรักษาความลับ
- วางโครงสร้างให้รองรับหลายสาขาในอนาคต โดย Phase 1 เปิดใช้งานเพียงหนึ่งสาขา

## 4. Actors และขอบเขตสิทธิ์

| Actor | หน้าที่และสิทธิ์ทางธุรกิจ |
| --- | --- |
| Website Guest Customer | จองผ่าน Public Website โดยใช้ชื่อเล่นและเบอร์โทรศัพท์ และติดตามสถานะผ่าน Booking ID กับ Secure Status Link |
| LINE-linked Customer | จองผ่าน LIFF/LINE Login หรือเชื่อม LINE ภายหลัง เพื่อรับการแจ้งเตือนผ่าน Customer LINE OA |
| LINE Admin Group Approver | ผู้ปฏิบัติงาน Admin/Staff ทุกคนใน LINE Group ที่ร้านลงทะเบียนไว้ สามารถดูสรุปการจองและรายละเอียดสุขภาพเพื่อเตรียมบริการ และยืนยัน Booking ที่เป็น `PENDING` ได้ โดยอยู่ภายใต้ข้อผูกพันด้านการรักษาความลับตามสัญญางาน |
| `ADMIN` | ใช้งาน Admin Web ได้ทั้งหมด รวมการจัดการผู้ใช้ บทบาท Security Configuration และการตั้งค่าระบบ |
| `STAFF` | จัดการ Booking, Customer Detail, Capacity, Slot, Service, ราคา, Therapist, Branch และการมอบหมายหมอนวด แต่ไม่มีสิทธิ์จัดการผู้ใช้ บทบาท หรือ Security Configuration |
| Therapist | ให้บริการตาม Booking ที่ได้รับมอบหมาย ไม่มีสิทธิ์เปลี่ยนกฎการจองใน Phase 1 |
| System | ตรวจ Availability, กัน Capacity, จัดการสถานะ, ส่ง Notification และเก็บ Audit Trail |

สิทธิ์ `ADMIN`/`STAFF` ของ Admin Web และสิทธิ์ LINE Admin Group เป็นคนละขอบเขตกัน การเป็นสมาชิก Registered Admin LINE Group ให้สิทธิ์รับสรุป Booking รวมรายละเอียดสุขภาพและยืนยัน Booking ผ่านกลุ่ม แต่ไม่ได้ให้สิทธิ์ Admin Web โดยอัตโนมัติ การเพิ่ม/ถอดสมาชิกกลุ่มเป็นกระบวนการควบคุมสิทธิ์ของร้าน และต้องถอดผู้พ้นหน้าที่ออกทันที

คำว่า “Admin” ที่ใช้ในกฎทั่วไปของเอกสารนี้หมายถึงผู้ใช้ Admin Web ที่ได้รับสิทธิ์ต่อการกระทำนั้น ซึ่งอาจเป็น `ADMIN` หรือ `STAFF`; เมื่อกฎต้องเป็น `ADMIN` เท่านั้นจะระบุ Role อย่างชัดเจน

## 5. ขอบเขต Phase 1

### 5.1 Customer Booking

- เปิดระบบจองจาก Rich Menu ของ Customer LINE OA หรือ Public Website
- รองรับ LIFF/LINE Login สำหรับลูกค้าที่เข้าผ่าน LINE แต่ไม่บังคับใช้ LINE เพื่อส่ง Booking
- Website Guest ใช้ชื่อเล่นและเบอร์โทรศัพท์เป็นข้อมูลระบุตัวตนที่จำเป็น โดยไม่บังคับชื่อ-นามสกุล Email การสมัครสมาชิก หรือ OTP
- LINE User ID เป็นข้อมูลทางเลือกและต้องได้รับจากการยืนยันตัวตนผ่าน LIFF/LINE Login หรือ Account Linking เท่านั้น
- เลือกบริการและระยะเวลา
- รองรับลูกค้า 1–2 คนต่อ Booking
- ลูกค้าแต่ละคนเลือกได้หนึ่งบริการและหนึ่งระยะเวลา
- ลูกค้าทุกคนใน Booking เดียวกันเริ่มรับบริการเวลาเดียวกัน
- ลูกค้าแต่ละคนสามารถเลือกบริการหรือระยะเวลาต่างกันได้
- ไม่รองรับการเลือกหลายบริการต่อเนื่องสำหรับลูกค้าคนเดียวใน Phase 1
- เลือกวันและเวลาจาก Slot ที่ระบบระบุว่าว่าง
- กรอกชื่อเล่นและ Health Declaration แยกตามผู้รับบริการ พร้อมเบอร์โทรศัพท์ของผู้ติดต่อหลัก
- Health Declaration เป็นคำถามบังคับ แต่ลูกค้าเลือก “ไม่มีข้อมูลสุขภาพที่ต้องแจ้ง” ได้ หากเลือกว่ามีจึงกรอกรายละเอียดที่จำเป็น
- แสดงสรุปรายการและราคาประเมินก่อนส่งคำขอ
- ชำระหลังให้บริการผ่านช่องทาง Beam ที่ร้านเปิดใช้ หรือให้ Admin บันทึกรับเงินสด โดยสถานะชำระเงินแยกจากสถานะ Booking
- ลูกค้าเลือกหมอนวดไม่ได้
- ลูกค้าไม่มี Self-service Reschedule หรือ Cancel ใน Phase 1
- หากต้องการเปลี่ยนแปลงหรือยกเลิก ลูกค้าต้องติดต่อร้านผ่าน LINE หรือโทรศัพท์

### 5.2 Admin Operations

- สร้าง Booking แบบ Staff-assisted จาก Admin Web สำหรับลูกค้า Walk-in วันนี้ ลูกค้าที่ติดต่อผ่าน LINE เพื่อจองล่วงหน้า และการบันทึกประวัติย้อนหลังที่พนักงานลืมลงระบบ
- Booking วันนี้หรืออนาคตต้องตรวจ Operating Hours, Slot Block และ Capacity แบบ Transaction และเริ่มต้นเป็น `CONFIRMED`
- วันที่/เวลาที่ผ่านไปแล้วสร้างได้เฉพาะโหมด `HISTORICAL_RECORD` เป็นสถานะปลายทาง `RECORDED`; ต้องเก็บ Price Snapshot, ราคาปกติ, ส่วนลด, ค่าบริการสุทธิ, ทิป และยอดรับรวมเป็นข้อมูลทางการเงินย้อนหลัง แต่ไม่กัน Capacity, ไม่สร้างธุรกรรมรับชำระหรือ Accounting Export อัตโนมัติ และไม่ส่ง Booking notification
- Staff-assisted Booking ใช้ชื่อเล่นเป็นข้อมูลขั้นต่ำ เบอร์โทรศัพท์เป็นข้อมูลทางเลือก และห้ามใช้เบอร์ร้านหรือเบอร์ปลอมแทนลูกค้าที่ไม่มีช่องทางติดต่อ
- เมื่อไม่มีเบอร์โทร ระบบไม่สร้าง Phone Guard, Phone Duplicate Key, Customer LINE Link หรือ Secure Status Link และต้องแสดงว่า `ไม่มีเบอร์ติดต่อ` ใน Admin Web
- Booking วันนี้หรืออนาคตที่สร้างโดย `ADMIN`/`STAFF` เริ่มต้นเป็น `CONFIRMED` ได้ เพราะผู้สร้างเป็นผู้ตรวจสอบและยืนยันรายการใน interaction เดียวกัน โดยต้องบันทึก Actor และ Audit Trail
- เฉพาะ Role `ADMIN` สามารถระบุส่วนลดจำนวนเงินบาทแบบไม่บังคับขณะสร้าง Booking วันนี้ อนาคต หรือย้อนหลังได้ และแก้/ยกเลิกส่วนลดของ Booking `COMPLETED` ก่อนชำระเงินได้ ต้องระบุเหตุผลหรือชื่อคูปองทุกครั้ง และระบบต้องแสดงราคาปกติ ส่วนลด และยอดสุทธิก่อนยืนยัน
- `ADMIN`/`STAFF` ระบุทิปจำนวนเงินบาทเต็มแบบไม่บังคับได้เฉพาะ `HISTORICAL_RECORD`; ระบบต้องเก็บทิปแยกจากค่าบริการและแสดงยอดรับรวม `ค่าบริการสุทธิ + ทิป` ก่อนบันทึก
- พนักงานต้องอ่าน Privacy Notice/Booking Terms และข้อความขอความยินยอมด้านข้อมูลสุขภาพให้ลูกค้ารับทราบ แล้วบันทึกวิธีรับหลักฐานเป็น `VERBAL` หรือ `PAPER`; ห้ามพนักงานให้ความยินยอมแทนลูกค้า
- ดู Booking แบบปฏิทิน รายการ และตารางเวลา
- ค้นหาด้วย Booking ID, ชื่อลูกค้า หรือเบอร์โทรศัพท์
- ดูรายละเอียดลูกค้าและข้อมูลสุขภาพในระบบ Admin
- แก้ไขวัน เวลา บริการ จำนวนลูกค้า และข้อมูลติดต่อ
- ยืนยัน Booking
- ยกเลิก Booking พร้อมบันทึกเหตุผล
- เปลี่ยนสถานะการให้บริการ
- ระบุ `NO_SHOW`
- Block/Unblock Slot
- กำหนด Capacity ของห้อง/เตียงและช่วงเวลา
- สร้าง แก้ไข เปิด หรือปิดบริการและราคา
- มอบหมายหรือเปลี่ยนหมอนวด
- ดูรายการ Booking ที่ยังไม่ได้มอบหมายหมอนวด

### 5.3 Admin Web Roles

- Phase 1 มี App Role เพียงสอง Role คือ `ADMIN` และ `STAFF`
- `ADMIN` ทำงาน Operational ทั้งหมดได้ และมีสิทธิ์เพิ่ม/ปิดผู้ใช้ กำหนด Role จัดการ Security Configuration และ System Configuration
- `STAFF` จัดการ Booking, Customer Detail, Capacity, Service, Therapist, Branch, Assignment และงานปฏิบัติการประจำวันได้
- `STAFF` ไม่มีสิทธิ์เพิ่ม/ปิดผู้ใช้ เปลี่ยน Role หรือแก้ Security Configuration
- `STAFF` ไม่มีสิทธิ์สร้างหรือแก้ส่วนลดของ Booking; การซ่อนช่องส่วนลดใน UI ไม่ทดแทนการตรวจสิทธิ์ที่ API
- ทั้ง `ADMIN` และ `STAFF` ที่เข้าสู่ระบบ Admin Web สามารถ Confirm หรือ Cancel Booking ตามกฎสถานะได้
- ทุกการเปลี่ยนแปลงสิทธิ์และทุกการดำเนินการสำคัญต้องมี Audit Trail

Loyalty, birthday automation, formula-driven payroll และ CRM campaign ไม่อยู่ใน Phase 1; Dashboard และการจัดสรรค่าหมอ/ทิปแบบ Admin กรอกเองอยู่ในขอบเขตตามหัวข้อ 19.2

## 6. Branch และ Operating Configuration

### 6.1 Branch

- Phase 1 มีหนึ่งสาขา
- Booking ทุกรายการต้องอ้างอิง Branch แม้ระบบจะแสดงเพียงสาขาเดียว
- ข้อมูลต้องสามารถขยายไปเป็นหลายสาขาได้ในอนาคต โดยแต่ละสาขามี Service, Operating Hours, Resource และ Booking Rules ของตนเอง

### 6.2 ค่าที่ Admin กำหนดได้

- ชื่อ ที่อยู่ เบอร์โทร และ URL แผนที่ของสาขา
- วันและเวลาทำการ
- วันหยุดหรือช่วงเวลาปิดพิเศษ
- ระยะเวลาจองล่วงหน้าขั้นต่ำและสูงสุด
- ห้อง เตียง พื้นที่บริการ และ Capacity
- Slot ที่เปิดรับหรือถูก Block
- Buffer time ระหว่าง Booking หากร้านต้องการ
- Service, duration variant, ราคา และสถานะ Active/Inactive
- ความสัมพันธ์ระหว่าง Service กับห้อง/เตียงที่รองรับ

ค่าเริ่มต้นของ Phase 1 คือเปิดทุกวันเวลา `10:00–22:00` ตามเวลา `Asia/Bangkok` โดย `ADMIN`/`STAFF` แก้เวลาทำการ วันหยุด และช่วงปิดพิเศษได้

## 7. Service และ Pax Rules

1. หนึ่ง Booking มีลูกค้าได้อย่างน้อย 1 คนและสูงสุด 2 คน
2. ลูกค้าแต่ละคนต้องมีหนึ่ง Service และหนึ่ง Duration Variant ยกเว้น Package ที่กำหนด `Required Pax = 2` ซึ่งการเลือกครั้งเดียวครอบคลุมผู้รับบริการสองคน
3. ลูกค้าทุกคนใน Booking ต้องมีเวลาเริ่มเดียวกัน
4. ระยะเวลาสิ้นสุดและการคืน Capacity คำนวณแยกตาม Service ของลูกค้าแต่ละคน
5. Package ที่ประกอบด้วยกิจกรรมหลายรายการสามารถขายเป็นหนึ่ง Service ได้ หาก Admin กำหนด duration รวมไว้แล้ว
6. Add-on จาก Stitch จะไม่ถูกซ้อนต่อท้าย Service ใน Phase 1 แต่ Admin สามารถตั้งรายการนั้นเป็น Service แบบจองเดี่ยวได้
7. Service ที่เป็น `INACTIVE` ต้องไม่แสดงในการจองใหม่ แต่ไม่เปลี่ยนข้อมูลย้อนหลังของ Booking เดิม
8. ราคาและระยะเวลาที่ลูกค้าเห็นต้องมาจาก Initial Service Catalog ที่ยืนยันแล้วหรือค่าที่ Admin แก้ไขและเปิดใช้งานภายหลัง
9. Service ทั่วไปคิดราคาแบบ `PER_PARTICIPANT`; Package สำหรับสองคนคิดราคาแบบ `PER_BOOKING` ครั้งเดียวและต้องกัน Resource ให้ครบสองคนตลอดระยะเวลา
10. ชื่อและคำอธิบายบริการแบบสั้นทั้งภาษาไทยและอังกฤษต้องเก็บใน Service Catalog/Firestore แก้ไขผ่าน Admin และแสดงจาก Active Service record เดียวกันบน Customer Web ห้าม hardcode แยกใน frontend

### 7.1 Initial Service Catalog

รายการเริ่มต้นต่อไปนี้ได้รับการยืนยันจาก `SPA-Customer-Views` และไฟล์ inventory `SPA/Document/DESING/Side-Customer/FLOW_STITCH.md` เมื่อ 14 สิงหาคม 2026:

| Category | Service (TH / EN) | Duration | Price | Pricing / Pax |
| --- | --- | ---: | ---: | --- |
| Signature Package | แพ็กเกจผ่อนคลายครบสูตร / Complete Relaxation Ritual | 105 นาที | 590 บาท | `PER_PARTICIPANT`, 1 คน |
| Signature Package | แพ็กเกจผ่อนคลายสำหรับสองท่าน / Couple Relaxation Package | 90 นาที | 1,190 บาท | `PER_BOOKING`, ต้องมี 2 คน |
| Massage | นวดเท้า / Reflexology Foot Massage | 60 / 120 นาที | 350 / 650 บาท | `PER_PARTICIPANT` |
| Massage | นวดแผนไทย / Traditional Thai Massage | 60 / 120 นาที | 300 / 600 บาท | `PER_PARTICIPANT` |
| Massage | นวดออย / น้ำมัน / Lamenatt Oil Massage | 60 / 120 นาที | 450 / 850 บาท | `PER_PARTICIPANT` |
| Massage | นวดแก้อาการ / Tendon Relief Massage | 60 / 120 นาที | 450 / 900 บาท | `PER_PARTICIPANT` |
| Massage | นวดน้ำมันอโรม่า / Aroma Therapy | 60 / 120 นาที | 600 / 1,200 บาท | `PER_PARTICIPANT` |
| Massage | นวดประคบสมุนไพร / Herbal Compress Massage | 60 / 120 นาที | 600 / 1,100 บาท | `PER_PARTICIPANT` |
| Massage | สครับผิวกาย / Body Scrub | 60 นาที | 600 บาท | `PER_PARTICIPANT` |
| Massage | อบสมุนไพร / Herbal Steam | 30 นาที | 300 บาท | `PER_PARTICIPANT` |
| Standalone Service | ประคบร้อน คอ บ่า ไหล่ / Hot Compress — Neck, Shoulder & Back | 20 นาที | 190 บาท | `PER_PARTICIPANT`; Phase 1 จองเดี่ยวเท่านั้น |

Initial catalog เป็นข้อมูล seed ที่ Admin แก้ไขชื่อ คำอธิบายสองภาษา ราคา ระยะเวลา Active State และ Resource Compatibility ได้ โดย Booking เก่าต้องเก็บ snapshot เดิมไว้ ชื่อ `Lamenatt Oil Massage` คงตาม source ชั่วคราวและ Admin แก้คำสะกดได้ก่อน Production

ข้อความ “Prices include 7% VAT” ที่อยู่ใน mockup ยังไม่เป็นกฎทางธุรกิจจนกว่านโยบาย VAT จะได้รับการยืนยัน

## 8. Booking Journey

ลำดับการจองที่เป็นทางการสำหรับ Phase 1:

```text
เลือกบริการ
  → เลือกจำนวนลูกค้าและบริการของแต่ละคน
  → เลือกวัน/เวลา
  → กรอกข้อมูลลูกค้าและข้อมูลสุขภาพ
  → ตรวจสอบสรุป
  → ส่งคำขอจอง
  → PENDING
  → ผู้มีสิทธิ์ตรวจสอบและยืนยัน
  → CONFIRMED
```

### 8.1 ขั้นตอนส่งคำขอ

1. ลูกค้าเปิด Booking App จาก Rich Menu/LIFF หรือเข้าผ่าน Public Website
2. หากเปิดผ่าน LIFF/LINE Login ระบบตรวจ Token ทาง Server และเชื่อม LINE User ID; หากเข้าผ่าน Public Website ลูกค้าดำเนินการต่อแบบ Guest ได้
3. ลูกค้าเลือก Service และ Duration เริ่มต้น
4. ลูกค้าเลือกจำนวน 1–2 คน และหากเลือก 2 คนให้ระบุ Service/Duration ของคนที่สอง
5. ระบบแสดงวันและ Slot ที่รองรับ Service, Duration และ Pax ที่เลือก
6. ลูกค้ากรอกชื่อเล่นและ Health Declaration แยกตามผู้รับบริการ พร้อมเบอร์โทรศัพท์ของผู้ติดต่อหลัก
7. ลูกค้าติ๊กยอมรับ Booking/Privacy Acknowledgement และ Explicit Health Consent แยกกันตามหัวข้อ 15.3; ต้องเก็บ version และเวลาที่ให้ความยินยอม
8. สำหรับ Website Guest ระบบตรวจ CAPTCHA, Rate Limit และกฎป้องกันคำขอซ้ำก่อนรับคำขอ
9. ระบบตรวจ Availability ซ้ำก่อนสร้าง Booking
10. หากยังว่าง ระบบสร้าง Booking ID, เปลี่ยนเป็น `PENDING` และกัน Capacity ทันที
11. ระบบแสดง Booking ID และสถานะรอยืนยัน; Website Guest ได้รับ Secure Status Link ส่วน LINE-linked Customer ได้รับ LINE Pending Acknowledgement
12. ระบบเสนอให้ Website Guest เชื่อม LINE เพื่อรับการแจ้งเตือน โดยเป็นทางเลือกและไม่เปลี่ยนผลการจองหากไม่เชื่อม
13. ระบบส่ง Flex Summary เข้า LINE Admin Group

หาก Slot ไม่ว่างแล้วในเวลาที่ลูกค้ากดส่ง ระบบต้องไม่สร้าง Booking และให้ลูกค้ากลับไปเลือกวัน/เวลาใหม่

### 8.2 Anonymous Booking Protection

Website Guest ไม่ใช้ OTP ใน Phase 1 จึงต้องมีกลไกต่อไปนี้:

- ตรวจ CAPTCHA ก่อน Submit
- จำกัดอัตราคำขอตาม IP Address และเบอร์โทรศัพท์
- ปฏิเสธคำขอซ้ำที่มีเบอร์โทรศัพท์ วัน และเวลาเดียวกันภายในช่วงเวลาที่กำหนด
- จำกัดจำนวน Booking สถานะ `PENDING` ที่ยัง Active ต่อเบอร์โทรศัพท์ โดย Admin ปรับค่าได้
- ให้ `ADMIN`/`STAFF` Block หรือยกเลิกคำขอจากเบอร์โทรศัพท์ที่ผิดปกติ พร้อมบันทึกเหตุผล
- การป้องกัน Abuse ไม่ทำให้ `PENDING` ที่สร้างสำเร็จแล้วหมดอายุอัตโนมัติ; Booking ดังกล่าวยังกัน Capacity จนถูก Confirm หรือ Cancel

ค่า Threshold, Window และ Challenge Policy ต้องกำหนดใน TDD และปรับได้ตาม Environment

## 9. Advance Booking Rules

- ค่าเริ่มต้นของระยะจองล่วงหน้าขั้นต่ำคือ 1 วัน
- ค่าเริ่มต้นของระยะจองล่วงหน้าสูงสุดคือ 30 วัน
- Admin สามารถปรับทั้งสองค่าได้
- การคำนวณใช้วันและเวลาของสาขาใน `Asia/Bangkok`
- ลูกค้าเลือก Slot ได้เฉพาะช่วงเวลาทำการที่ไม่ถูก Block และมี Capacity เพียงพอ
- เมื่อ Admin เปลี่ยนกฎ ค่าใหม่ใช้กับการจองใหม่ ไม่ยกเลิก Booking ที่มีอยู่โดยอัตโนมัติ
- กฎ Min/Max Advance Booking ใช้กับ Customer Web และ LIFF; Admin Staff-assisted Booking เลือกวันวันนี้หรืออนาคตได้โดยไม่ใช้ Min/Max Window แต่ยังต้องผ่าน Availability และ Capacity
- วัน/เวลาที่ผ่านไปแล้วต้องใช้ `HISTORICAL_RECORD` เท่านั้น และไม่ถือเป็นการจอง Capacity ย้อนหลัง

## 10. Availability และ Capacity Logic

Availability ใน Phase 1 อิงห้อง เตียง พื้นที่บริการ และ Capacity ที่ Admin กำหนด ไม่อิงตารางหมอนวด

### 10.1 Capacity Consumption

Booking ต่อไปนี้ใช้ Capacity:

- `PENDING`
- `CONFIRMED`
- `IN_SERVICE`

Booking ต่อไปนี้ไม่ใช้ Capacity:

- `COMPLETED`
- `CANCELLED`
- `NO_SHOW`

### 10.2 กฎการกัน Capacity

1. ระบบต้องตรวจ Availability ครบทุก Resource และตลอด Duration ที่ต้องใช้
2. Booking จำนวน 2 คนต้องมี Capacity พร้อมกันสำหรับทั้งสองคน ณ เวลาเริ่มเดียวกัน
3. ถ้าบริการใช้เวลาต่างกัน Resource ของแต่ละคนถูกคืนตามเวลาสิ้นสุดของบริการนั้น รวม Buffer ที่ตั้งค่าไว้
4. `PENDING` กัน Capacity ทันทีและไม่มี Auto-expiration
5. `PENDING` คงอยู่จนกว่า Admin หรือผู้มีสิทธิ์จะ `CONFIRM` หรือ `CANCEL`
6. Admin ต้องเห็น Pending Queue เพื่อป้องกัน Booking ค้างและ Capacity ถูกกันโดยไม่จำเป็น
7. การสร้างหรือแก้ไข Booking ต้องตรวจ Capacity แบบป้องกันการจองซ้ำ โดยคำขอแรกที่สำเร็จเป็นผู้ได้ Capacity
8. เมื่อ Admin ย้ายวัน เวลา Service หรือ Pax ระบบต้องตรวจ Capacity ใหม่ก่อนบันทึก
9. Slot ที่ Admin Block ต้องไม่รับ Booking ใหม่ แต่ Booking เดิมต้องถูกแจ้งเตือนให้ Admin จัดการ ไม่ถูกยกเลิกอัตโนมัติ

การเลือกให้ `PENDING` ไม่มีวันหมดอายุเป็น Business Decision ของ Phase 1 และต้องถูกติดตามเป็น Operational Risk ใน HLD/TDD

## 11. Booking Status Lifecycle

```text
PENDING ───────→ CONFIRMED ───────→ IN_SERVICE ───────→ COMPLETED
   │                 │
   └──→ CANCELLED ←──┘
                     └──→ NO_SHOW

RECORDED ───────→ CANCELLED
```

| Status | ความหมาย | Capacity | ผู้เปลี่ยนสถานะ |
| --- | --- | --- | --- |
| `PENDING` | ลูกค้าส่งคำขอแล้ว รอร้านตรวจสอบ | ใช้ | System สร้าง; LINE Approver/`ADMIN`/`STAFF` ดำเนินการต่อ |
| `CONFIRMED` | ร้านรับรองวัน เวลา Service และ Capacity แล้ว | ใช้ | LINE Group Approver, `ADMIN` หรือ `STAFF` |
| `IN_SERVICE` | ลูกค้าเริ่มรับบริการ | ใช้ | `ADMIN`/`STAFF` |
| `COMPLETED` | ให้บริการเสร็จแล้ว | ไม่ใช้ | `ADMIN`/`STAFF` |
| `RECORDED` | ประวัติบริการย้อนหลังพร้อมยอดทางการเงิน | ไม่ใช้ | `ADMIN`/`STAFF` สร้างหรือยกเลิกเมื่อบันทึกผิด |
| `CANCELLED` | ร้านหรือลูกค้าติดต่อให้ยกเลิก โดยผู้ใช้ Admin Web บันทึกเหตุผล | ไม่ใช้ | `ADMIN`/`STAFF` |
| `NO_SHOW` | Booking ที่ Confirm แล้วแต่ลูกค้าไม่มาตามนัด | ไม่ใช้ | `ADMIN`/`STAFF` |

### 11.1 Transition Rules

- Booking ใหม่จาก Customer Web หรือ LIFF เริ่มต้นเป็น `PENDING` เสมอ
- Staff-assisted Booking วันนี้หรืออนาคตที่สร้างโดย `ADMIN`/`STAFF` ผ่าน Admin Web เริ่มต้นเป็น `CONFIRMED` และ Audit ต้องระบุ `source=ADMIN_WEB`, ผู้สร้าง และการยืนยันใน interaction เดียวกัน
- Historical record เริ่มต้นที่ `RECORDED`; ต้องระบุ `financiallyExcluded=false`, `historicalFinancialRecord=true`, ผู้บันทึก ราคาปกติ ส่วนลด ค่าบริการสุทธิ ทิป ยอดรับรวม และเวลาที่บันทึกใน Audit
- `PENDING → CONFIRMED` ทำได้ครั้งเดียว
- `PENDING → CANCELLED` ทำได้โดย `ADMIN`/`STAFF` พร้อมเหตุผล
- `CONFIRMED → IN_SERVICE` ต้องมีหมอนวดถูกมอบหมายแล้ว
- `CONFIRMED → CANCELLED` ต้องมีเหตุผล
- `CONFIRMED → NO_SHOW` ใช้เมื่อลูกค้าไม่มาตามนัดเท่านั้น
- `IN_SERVICE → COMPLETED` ใช้เมื่อจบการให้บริการ
- `RECORDED → CANCELLED` ทำได้โดย `ADMIN`/`STAFF` เฉพาะเพื่อแก้รายการย้อนหลังที่บันทึกผิด ต้องมีเหตุผล ตั้ง `financiallyExcluded=true`, ไม่เปลี่ยน Capacity และไม่สร้าง Notification Outbox
- `COMPLETED`, `CANCELLED` และ `NO_SHOW` เป็นสถานะปลายทาง การเปิด Booking กลับมาใหม่ต้องเป็นการดำเนินการที่มี Audit Trail
- คำสั่งซ้ำหรือคำสั่งที่ขัดกับสถานะปัจจุบันต้องไม่เปลี่ยนข้อมูลซ้ำ

## 12. Therapist Assignment

- ลูกค้าไม่สามารถเลือกหมอนวดได้
- Availability ของ Customer Booking ไม่พิจารณาตารางหมอนวดใน Phase 1
- Booking สามารถเปลี่ยนเป็น `CONFIRMED` ได้แม้ยังไม่ได้มอบหมายหมอนวด
- `ADMIN`/`STAFF` เป็นผู้มอบหมายหรือเปลี่ยนหมอนวดภายหลัง
- ต้องมอบหมายหมอนวดให้ผู้รับบริการทุกคนก่อนเปลี่ยนเป็น `IN_SERVICE`
- ระบบต้องแสดง Unassigned Booking Queue
- การเปลี่ยนหมอนวดไม่เปลี่ยนวัน เวลา ราคา หรือสถานะ Booking โดยอัตโนมัติ

## 13. LINE Admin Group Approval

### 13.1 Admin LINE OA

- ร้านใช้ Admin LINE OA สำหรับ LINE Admin Group โดยแยกจาก Customer LINE OA
- Admin LINE OA ต้องถูกเชิญเข้า Group ที่ร้านลงทะเบียนไว้
- ใน Admin Group ให้มีเฉพาะ Admin LINE OA; Customer LINE OA ไม่ถูกเชิญเข้ากลุ่มดังกล่าว
- ระบบรับเฉพาะ Approval Event จาก Group ID ที่ลงทะเบียนและเปิดใช้งาน
- สมาชิกทุกคนใน Group ต้องเป็นผู้ปฏิบัติงานที่ร้านอนุญาตและมีข้อผูกพันด้านการรักษาความลับ
- ผู้ดูแลร้านต้องทบทวนสมาชิกกลุ่มเป็นระยะและถอดผู้พ้นหน้าที่ออกทันที
- สมาชิกทุกคนใน Group ที่ระบุตัวตนได้มีสิทธิ์ Confirm Booking

### 13.2 New Booking Flex Summary

Flex Summary ที่ส่งเข้ากลุ่มต้องมีอย่างน้อย:

- Booking ID
- สถานะ `PENDING`
- ชื่อและเบอร์โทรศัพท์ลูกค้า
- วันและเวลา
- Service และ Duration ของผู้รับบริการแต่ละคน
- จำนวนลูกค้า
- รายละเอียด Health Declaration ที่ลูกค้าแจ้ง แยกตามผู้รับบริการ
- ปุ่มโทรหาลูกค้า
- ปุ่มยืนยัน Booking

เมื่อผู้รับบริการแจ้งข้อมูลสุขภาพ Flex Summary ต้องแสดงชื่อเล่นและข้อความที่ลูกค้ากรอก เพื่อให้ Admin/Staff เตรียมบริการได้โดยไม่ต้องเปิด Admin Web ข้อมูลนี้ส่งได้เฉพาะ Registered Admin LINE Group เท่านั้น ห้ามส่งไป Customer Group, Group อื่น, log, URL, task payload หรือ operational alert และระบบต้อง Audit การเปิดเผยโดยไม่คัดลอกรายละเอียดสุขภาพลง Audit

### 13.3 Approval Action

- ปุ่มยืนยันใช้ LINE `message action` เพื่อส่งคำสั่งยืนยันใน Group
- ระบบต้องตรวจความถูกต้องของ Webhook และตรวจว่า Event มาจาก Group ID ที่ลงทะเบียน
- Event ต้องมี User ID ของผู้กดเพื่อบันทึกผู้อนุมัติ
- ถ้าไม่สามารถระบุตัวผู้กดได้ ระบบต้องไม่ Confirm และให้ดำเนินการผ่าน Admin Web
- ระบบ Confirm ได้เฉพาะ Booking ที่เป็น `PENDING`
- การ Confirm ต้องเป็น Atomic Operation เพื่อป้องกันสมาชิกหลายคนกดพร้อมกัน
- ผู้กดคนแรกที่สำเร็จเป็นผู้อนุมัติ ส่วนผู้กดภายหลังได้รับข้อความว่า Booking ถูกดำเนินการแล้ว
- Audit Trail ต้องเก็บ Booking ID, Group ID, Approver LINE User ID, เวลา, สถานะเดิม และสถานะใหม่
- หลัง Confirm ระบบส่งข้อความตอบกลับใน Group ว่าใครยืนยัน Booking ใดและเวลาใด

การใช้ URL ยืนยันแบบสาธารณะที่ไม่มีการยืนยันตัวตนไม่อนุญาต เพราะ URL อาจถูกส่งต่อออกนอก Group ได้

## 14. Customer Status และ Notifications

Customer LINE OA เป็นคนละบัญชีกับ Admin LINE OA

Customer LIFF/LINE Login และ Customer Messaging API Channel ต้องอยู่ภายใต้ LINE Provider เดียวกัน เพื่อให้ Customer LINE User ID ที่ใช้ระบุตัวตนและส่งข้อความสอดคล้องกัน

LINE Notification ใช้เฉพาะ Booking ที่มี LINE User ID เชื่อมอยู่และสามารถรับข้อความจาก Customer LINE OA ได้ ส่วน Website Guest ที่ยังไม่เชื่อม LINE ต้องติดตามผ่าน Secure Status Link โดย Phase 1 ไม่มี SMS Notification

### 14.1 Pending Acknowledgement

หลังสร้าง Booking สำเร็จ ระบบต้องแสดงผลยืนยันทันที และส่ง LINE Pending Acknowledgement เมื่อ Booking เชื่อม LINE แล้ว โดยมีข้อมูลอย่างน้อย:

- ร้านได้รับคำขอแล้ว
- Booking ID
- สถานะ `PENDING`
- วัน เวลา Service และจำนวนลูกค้า
- คำขอยังไม่ถือว่าได้รับการยืนยันจนกว่าร้านจะส่งข้อความ `CONFIRMED`
- ช่องทางติดต่อร้าน

สำหรับ Website Guest ระบบต้องแสดง Booking ID และ Secure Status Link ในหน้าผลลัพธ์ พร้อมแจ้งให้บันทึกลิงก์ไว้ และเสนอการเชื่อม LINE เพื่อรับการแจ้งเตือนเป็นทางเลือก

### 14.2 Confirmation Flex Summary

เมื่อ Booking ที่เชื่อม LINE เปลี่ยนเป็น `CONFIRMED` ระบบส่ง Flex Summary ซึ่งมีอย่างน้อย:

- Booking ID
- ชื่อลูกค้า
- วันและเวลา
- Service และ Duration
- จำนวนลูกค้า
- ราคาประเมินรวม
- คำแนะนำให้มาถึงก่อนเวลานัด
- เงื่อนไขให้ติดต่อร้านล่วงหน้าหากต้องการเปลี่ยนแปลง
- ปุ่มแผนที่ร้าน

ห้ามส่งรายละเอียดสุขภาพกลับไปใน Flex Summary

Website Guest ที่ยังไม่เชื่อม LINE เห็นสถานะ `CONFIRMED` ผ่าน Secure Status Link และร้านใช้เบอร์โทรศัพท์เป็นช่องทางสำรองเมื่อจำเป็น

### 14.3 Notification จากการเปลี่ยนแปลง

- เมื่อ Admin ยกเลิก Booking ระบบต้องอัปเดต Secure Status Page และส่ง LINE พร้อมเหตุผลที่เหมาะสมต่อการเปิดเผยเมื่อ Booking เชื่อม LINE แล้ว
- เมื่อ Admin เปลี่ยนวัน เวลา Service, Pax หรือราคาของ Booking ที่ Confirm แล้ว ระบบต้องอัปเดต Secure Status Page และส่งสรุปฉบับปรับปรุงเมื่อ Booking เชื่อม LINE แล้ว
- หากส่ง LINE ไม่สำเร็จ Booking ยังคงสถานะที่เปลี่ยนแล้ว แต่ระบบต้องแสดง Notification Failure ให้ Admin ติดตามลูกค้าทางโทรศัพท์
- การส่ง Notification ซ้ำต้องไม่ทำให้ Booking เปลี่ยนสถานะซ้ำ

### 14.4 Secure Status Link และ LINE Account Linking

- Secure Status Link ต้องใช้ Token ที่คาดเดาไม่ได้และไม่ใส่ชื่อ เบอร์โทรศัพท์ หรือข้อมูลสุขภาพใน URL
- Link แสดงเฉพาะข้อมูล Booking ที่จำเป็นต่อการติดตามสถานะ และไม่เปิดเผย Health Detail
- อายุ การเพิกถอน และการออก Link ใหม่เป็น Security Configuration ที่กำหนดรายละเอียดใน TDD
- Website Guest สามารถเลือกเชื่อม LINE หลังสร้าง Booking ผ่าน Account Linking Flow ที่ระบบตรวจสอบแล้ว
- เมื่อเชื่อมสำเร็จ ระบบผูก LINE User ID กับ Booking/Customer และส่ง LINE Notification สำหรับเหตุการณ์หลังจากนั้น
- การไม่เชื่อม LINE ไม่ยกเลิก Booking และไม่เปลี่ยนสถานะหรือ Capacity

## 15. Customer Data และ Health Information

### 15.1 ข้อมูลที่จำเป็นใน Phase 1

| Data | Required | วัตถุประสงค์ |
| --- | --- | --- |
| LINE User ID | ไม่บังคับ | เชื่อม Booking และส่ง Notification เมื่อผ่าน LIFF/LINE Login หรือ Account Linking |
| ชื่อเล่น | ใช่ แยกตามผู้รับบริการ | ระบุผู้รับบริการด้วยข้อมูลขั้นต่ำที่ใช้ในงานหน้าร้าน |
| ชื่อ-นามสกุล | ไม่ใช่ | ไม่บังคับใน Phase 1 |
| เบอร์โทรศัพท์ | ใช่ อย่างน้อยหนึ่งหมายเลขต่อ Booking | ติดต่อผู้ติดต่อหลักกรณี Booking หรือ Notification มีปัญหา |
| Email | ไม่ใช่ | ไม่อยู่ใน Phase 1 |
| Health Declaration | ต้องตอบแยกตามผู้รับบริการ | ยืนยันว่ามีหรือไม่มีข้อมูลสุขภาพที่ร้านต้องตรวจสอบ |
| รายละเอียดสุขภาพ/โรคประจำตัว/อาการแพ้ | เมื่อ Health Declaration ระบุว่ามี | ความปลอดภัยในการให้บริการ |
| วันเกิด | ไม่ใช่ | Phase 2 |

### 15.2 Privacy Rules

- ก่อนส่ง Booking ลูกค้าต้องรับทราบวัตถุประสงค์การเก็บและใช้ข้อมูล
- เก็บเฉพาะข้อมูลสุขภาพที่จำเป็นต่อความปลอดภัยในการให้บริการ
- รายละเอียดสุขภาพดูได้โดยผู้มีสิทธิ์ใน Admin System และสมาชิก Registered Admin LINE Group ที่ร้านควบคุมสมาชิกตามหน้าที่งาน
- Admin Booking Flex แสดงรายละเอียดที่ลูกค้าแจ้งแยกตามผู้รับบริการ เพื่อเตรียมบริการและยืนยัน Booking ให้จบใน LINE
- ห้ามใส่รายละเอียดสุขภาพใน Customer Flex, LINE Group อื่น, log ทั่วไป, operational alert, task payload หรือ URL
- Secure Status Page ต้องไม่แสดงรายละเอียดสุขภาพ และต้องเข้าถึงด้วย Token ที่คาดเดาไม่ได้
- การเปิดดูและแก้ไขข้อมูลสุขภาพต้องมี Audit Trail ตามระดับที่กำหนดใน HLD/TDD
- ระบบสร้าง Customer Profile เพื่อใช้ข้อมูลติดต่อและ Health Profile ที่เป็นปัจจุบันซ้ำในครั้งถัดไป โดย `ADMIN` และ `STAFF` แก้ไขได้
- ทุก Booking ต้องเก็บ Health Snapshot ของวันที่จอง/รับบริการแยกจาก Health Profile เพื่อไม่ให้การแก้ Profile ภายหลังเปลี่ยนประวัติย้อนหลัง
- LINE-linked Customer สามารถเชื่อม Profile ด้วย LINE User ID ที่ตรวจสอบแล้ว ส่วน Website Guest ห้ามถูก merge หรือเปิดประวัติด้วยเบอร์โทรศัพท์เพียงอย่างเดียว; `ADMIN`/`STAFF` ต้องตรวจสอบตัวบุคคลก่อน reconcile/merge Profile
- การแก้ Health Profile หรือ merge Customer Profile ต้องเก็บ Audit Trail โดย Audit ห้ามบันทึกรายละเอียดสุขภาพแบบ plaintext
- Health Profile มีลักษณะต่อเนื่องข้าม Booking แต่ไม่ควรกำหนดเป็น “เก็บตลอดไปโดยไม่มีเงื่อนไข”; ระยะเวลาเก็บ การถอนความยินยอม และการลบ/ทำให้ไม่สามารถระบุตัวบุคคลต้องได้รับอนุมัติก่อน Production

### 15.3 Consent Wording Baseline

หน้า Review ต้องมี checkbox แยกกันและไม่ถูกเลือกไว้ล่วงหน้า:

**A. Booking and Privacy Acknowledgement — required**

> ฉันยืนยันว่าข้อมูลการจองและข้อมูลติดต่อที่ให้ไว้ถูกต้อง และรับทราบนโยบายความเป็นส่วนตัวและเงื่อนไขการจองของ SPA 49

คำว่า “นโยบายความเป็นส่วนตัว” และ “เงื่อนไขการจอง” ต้องเป็น Link เปิดอ่านได้ก่อน Submit

**B. Explicit Health Data Consent — required per participant when health data is collected or retained**

> ฉันยินยอมโดยชัดแจ้งให้ SPA 49 เก็บรวบรวม ใช้ และปรับปรุงข้อมูลสุขภาพ อาการ โรคประจำตัว และการแพ้ที่ฉันแจ้ง เพื่อประเมินความเหมาะสมและความปลอดภัยในการให้บริการนวด/สปา จัดเตรียมบริการ และเก็บเป็นประวัติลูกค้าสำหรับการรับบริการครั้งถัดไป รวมถึงส่งรายละเอียดดังกล่าวไปยัง Registered Admin LINE Group ซึ่งจำกัดสมาชิกเฉพาะผู้ปฏิบัติงานที่ได้รับอนุญาตและมีหน้าที่รักษาความลับ ทั้งนี้ ฉันสามารถถอนความยินยอมหรือขอใช้สิทธิตามนโยบายความเป็นส่วนตัวได้

เมื่อผู้ติดต่อหลักกรอกข้อมูลให้ผู้รับบริการคนที่สอง ต้องมี checkbox เพิ่มเติม:

> ฉันยืนยันว่าได้รับอนุญาตจากผู้รับบริการคนนี้ให้กรอกและส่งข้อมูลสุขภาพเพื่อวัตถุประสงค์ด้านความปลอดภัยในการให้บริการตามที่แจ้งไว้

ระบบต้องเก็บ `consentVersion`, เวลาที่ให้ความยินยอม, ช่องทาง, Participant และหลักฐานผู้ดำเนินการ โดยห้ามใช้ checkbox เดียวรวม Consent สุขภาพกับ Marketing Consent ในอนาคต

### 15.4 Proposed Health Retention Decision

ข้อเสนอสำหรับอนุมัติก่อน Production คือเก็บ Health Profile และ Health Snapshot เป็นเวลา **3 ปีนับจากวันที่รับบริการที่ `COMPLETED` ล่าสุด หรือวันที่เก็บ/แก้ข้อมูลสุขภาพล่าสุดหากยังไม่มี Visit ที่ Completed** และต่ออายุเมื่อมี Visit หรือการแก้ข้อมูลที่ได้รับอนุญาตใหม่ จากนั้นลบหรือทำให้ไม่สามารถระบุตัวบุคคลได้ เว้นแต่ยังมีฐานกฎหมายอื่นที่บันทึกไว้ การถอนความยินยอมต้องหยุดใช้ข้อมูลในอนาคตและเข้าสู่ workflow ตรวจสอบการลบ/จำกัดการใช้

ระยะเวลา 3 ปีเป็นข้อเสนอทางธุรกิจและสถาปัตยกรรม ไม่ใช่ข้อกำหนดตายตัวของกฎหมาย จึงยังเป็น Production Release Gate จนกว่า Product Owner จะอนุมัติและ Privacy Notice ผ่านการตรวจทาน

## 16. Price และ Payment Rules

- สกุลเงิน Phase 1 คือ THB
- Admin เป็นผู้กำหนดราคา Service และ Duration Variant
- ระบบเก็บ Price Snapshot ตอนสร้าง Booking เพื่อไม่ให้การเปลี่ยนราคาในอนาคตแก้ยอดย้อนหลัง
- ราคาปกติรวมเท่ากับผลรวม Line Item ที่คิดแบบ `PER_PARTICIPANT` และ Package `PER_BOOKING` อย่างละหนึ่งครั้ง ห้ามคิด Couple Package ซ้ำตามจำนวนผู้รับบริการ
- ส่วนลด Booking เป็นจำนวนเงินบาทเต็มเท่านั้น มีค่าเริ่มต้น 0 ต้องน้อยกว่าราคาปกติรวม และใช้ได้กับ Booking ที่มีผลทางการเงินรวมถึง `HISTORICAL_RECORD`
- ยอดสุทธิของ Booking เท่ากับ `subtotalAmountSatang - discountAmountSatang`; ระบบต้องเก็บ Price Snapshot เดิมไว้ ไม่แก้ราคาต้นฉบับของ Service line
- Admin สามารถบันทึกผลของ Coupon เป็นส่วนลด Booking พร้อมเหตุผล เช่น `คูปองสมัครครั้งแรก`; การค้นหาและ Redeem coupon code จริงยังเป็น transaction แยก และข้อความเหตุผลเพียงอย่างเดียวต้องไม่เปลี่ยนสถานะ Coupon
- การให้ส่วนลดต้องเก็บผู้ดำเนินการ เวลา เหตุผล ราคาปกติ ส่วนลด และยอดสุทธิใน Audit Trail
- การแก้หรือยกเลิกส่วนลดหลังจบบริการทำได้เฉพาะ `COMPLETED` ที่ Payment ยังเป็น `DUE`, ไม่มี Beam attempt ที่ Active/ต้อง Reconcile และไม่มี Correction Hold; หลัง `PAID` ต้องใช้ Refund/Correction flow แยก
- การแก้ส่วนลดก่อนชำระต้องอัปเดต Booking และ Payment snapshot ใน Transaction เดียวด้วย optimistic Booking version; หากมี Settlement เดิมต้องทำเป็น `STALE` และไม่นำมารวม Dashboard/Insight จน Admin ตรวจและบันทึกใหม่
- Booking Status และ Payment Status เป็นคนละ state machine; ห้ามเปลี่ยน Booking เป็น `PAID`
- ยอดรับเงินจริงเกิดจาก Beam ที่ตรวจสอบกับ Provider แล้ว หรือการบันทึกรับเงินสดแบบ idempotent โดย Admin
- ทิปต้องเก็บแยกจากค่าบริการ และ Payment ที่เปลี่ยนทิปต้องสะท้อนยอด Tip/Gross ล่าสุดกลับไปที่ Booking เพื่อใช้ตรวจ Settlement
- นโยบาย VAT และข้อความทางภาษีต้องได้รับการยืนยันก่อน Production ไม่ใช้ข้อความตัวอย่างใน Stitch เป็นข้อสรุป

## 17. Admin Change Rules

- Admin แก้ข้อมูลติดต่อได้โดยไม่เปลี่ยนสถานะ Booking
- การเปลี่ยนวัน เวลา Service, Duration หรือ Pax ต้องตรวจ Capacity ใหม่
- หาก Capacity ใหม่ไม่พอ ระบบต้องไม่บันทึกการเปลี่ยนแปลง
- การแก้ Booking ที่ `CONFIRMED` ต้องคง Capacity เดิมไว้จนกว่าการจอง Resource ใหม่จะสำเร็จ เพื่อไม่ให้ Booking สูญเสีย Slot จากความผิดพลาดระหว่างเปลี่ยน
- การยกเลิกต้องมีเหตุผลและคืน Capacity ทันที
- ทุกการเปลี่ยนแปลงที่มีผลต่อ Booking ต้องเก็บผู้ดำเนินการ เวลา ค่าเดิม และค่าใหม่

## 18. Failure และ Exception Rules

| เหตุการณ์ | พฤติกรรมที่ต้องการ |
| --- | --- |
| Slot เต็มระหว่างกรอกแบบฟอร์ม | ไม่สร้าง Booking และให้เลือก Slot ใหม่ |
| สมาชิกหลายคนกด Confirm พร้อมกัน | สำเร็จเพียงครั้งเดียว คนอื่นได้รับสถานะล่าสุด |
| LINE Admin Notification ส่งไม่สำเร็จ | Booking ยังคง `PENDING` และ Admin Web แสดงรายการพร้อมแจ้งเตือนความล้มเหลว |
| Customer Pending LINE Notification ส่งไม่สำเร็จ | Booking ยังคง `PENDING`; Secure Status Page ยังใช้ได้ และ Admin เห็น Failure |
| Customer Confirmation LINE ส่งไม่สำเร็จ | Booking ยังคง `CONFIRMED`; Secure Status Page แสดงสถานะล่าสุด และ Admin ต้องติดต่อทางโทรศัพท์เมื่อจำเป็น |
| Admin OA ออกจาก Group | หยุดรับ Approval จาก Group และแจ้ง Configuration Error ใน Admin Web |
| Website Guest ไม่มี LINE User ID | อนุญาตให้จองด้วยชื่อเล่นและเบอร์โทร; ให้ Booking ID กับ Secure Status Link และไม่ส่ง LINE จนกว่าจะเชื่อมบัญชี |
| CAPTCHA หรือ Rate Limit ไม่ผ่าน | ไม่สร้าง Booking และไม่กัน Capacity; แสดงข้อความให้ลองใหม่หรือติดต่อร้าน |
| คำขอ Guest ซ้ำหรือเกิน Active Pending Limit | ไม่สร้าง Booking เพิ่ม; แสดง Booking ที่เกี่ยวข้องเมื่อทำได้อย่างปลอดภัย หรือให้ติดต่อร้าน |
| Resource ถูกปิดหลังมี Booking | ไม่ยกเลิก Booking อัตโนมัติ; แจ้ง Admin ให้ย้ายหรือยกเลิก |
| Booking `PENDING` ค้าง | ยังคงกัน Capacity; แสดงเด่นใน Pending Queue จนกว่า Admin จะดำเนินการ |

## 19. Phase 1 Acceptance Rules

| ID | Business Acceptance Rule |
| --- | --- |
| BL-BKG-001 | ลูกค้าจองจาก LINE Rich Menu/LIFF หรือ Public Website ตามลำดับ Service → Pax → Date/Time → Customer Data → Confirmation ได้ |
| BL-BKG-002 | หนึ่ง Booking รองรับ 1–2 คน และแต่ละคนมีหนึ่ง Service/Duration |
| BL-BKG-003 | ลูกค้าเลือกหมอนวดไม่ได้ |
| BL-BKG-004 | Booking ใหม่ต้องเป็น `PENDING` และกัน Capacity ทันที |
| BL-BKG-005 | `PENDING` ไม่มี Auto-expiration และคงอยู่จนถูก Confirm/Cancel |
| BL-BKG-006 | Website Guest จองได้ด้วยชื่อเล่น เบอร์โทรศัพท์ และ Health Declaration โดยไม่ต้อง LINE Login, สมัครสมาชิก หรือ OTP |
| BL-BKG-007 | Guest Booking ที่สร้างสำเร็จต้องได้รับ Booking ID และ Secure Status Link |
| BL-BKG-008 | Website Guest ต้องผ่าน CAPTCHA, Rate Limit, Duplicate Check และ Active Pending Limit ก่อนสร้าง Booking |
| BL-CAP-001 | Slot แสดงว่างเฉพาะเมื่อห้อง/เตียงเพียงพอตลอด Duration ของทุกคน |
| BL-CAP-002 | Booking และการแก้ไขที่ชน Capacity ต้องถูกปฏิเสธ |
| BL-CAP-003 | Admin Block Slot ได้โดยไม่ลบ Booking เดิมอัตโนมัติ |
| BL-ADM-001 | สมาชิกใน LINE Admin Group ที่ลงทะเบียนและระบุตัวตนได้ Confirm Booking ได้ |
| BL-ADM-002 | การกด Confirm ซ้ำหรือพร้อมกันเปลี่ยนสถานะสำเร็จได้เพียงครั้งเดียว |
| BL-ADM-003 | ระบบบันทึก Approver และ Audit Trail ของการ Confirm |
| BL-ADM-004 | Admin Web มี App Role เพียง `ADMIN` และ `STAFF`; ทั้งสอง Role ทำงาน Operational ได้ แต่เฉพาะ `ADMIN` จัดการผู้ใช้ Role และ Security Configuration ได้ |
| BL-ADM-005 | สิทธิ์ LINE Group Approval แยกจาก Admin Web Role และไม่ให้สิทธิ์ Admin Web โดยอัตโนมัติ |
| BL-LINE-001 | Registered Admin LINE Group ได้รับ New Booking Flex พร้อมรายละเอียดสุขภาพที่ลูกค้าแจ้งแยกตามผู้รับบริการ โดย Customer Flex, Group อื่น, task, URL และ log ต้องไม่มีรายละเอียดดังกล่าว |
| BL-LINE-002 | LINE-linked Customer ได้รับข้อความ `PENDING` หลังส่งคำขอสำเร็จ |
| BL-LINE-003 | LINE-linked Customer ได้รับ Confirmation Flex หลัง Booking เป็น `CONFIRMED` |
| BL-LINE-004 | Notification Failure ไม่ Rollback สถานะ Booking และต้องแจ้ง Admin |
| BL-LINE-005 | Website Guest เลือกเชื่อม LINE หลัง Booking ได้ แต่การไม่เชื่อมไม่กระทบสถานะหรือ Capacity |
| BL-LINE-006 | Phase 1 ส่ง Operational Alert ออกไปที่ LINE Admin Group ที่ลงทะเบียนไว้เท่านั้น; ไม่มี Email, SMS หรือ Alert Destination อื่น |
| BL-OPS-001 | Booking Confirm ได้ก่อนมอบหมายหมอนวด แต่เริ่มบริการไม่ได้จนกว่าจะมอบหมายครบ |
| BL-OPS-002 | ลูกค้าเปลี่ยนหรือยกเลิกด้วยตนเองไม่ได้ใน Phase 1 และต้องติดต่อร้าน |
| BL-OPS-003 | Booking สองคนต้องมอบหมายหมอนวดที่ Active คนละคนต่อผู้รับบริการ และบันทึกจาก Booking Detail ได้โดยไม่ต้องออกจากคิวรายการจอง |
| BL-PAY-001 | สถานะการให้บริการและสถานะการชำระเงินต้องแยกจากกัน โดยยอดรับเงินจริงยืนยันจาก Beam หรือการบันทึกรับเงินสดโดย Admin เท่านั้น |
| BL-FIN-001 | เฉพาะ `ADMIN` บันทึกหรือแก้ไขการแบ่งค่าหมอและทิปได้ และทุกครั้งต้องมี Audit Trail |
| BL-FIN-002 | ค่าหมอกำหนดเป็นจำนวนเงินบาทต่อผู้รับบริการและต่อหมอนวดได้อย่างอิสระ ส่วนลดเป็น Promotion ของร้านและไม่ลดฐานค่าหมออัตโนมัติ |
| BL-FIN-003 | ทิปแบ่งให้หมอนวดหลายคนได้ ยอดที่เหลือเป็นของร้าน และผลรวมส่วนแบ่งหมอนวดต้องไม่เกินทิปที่รับจริง |
| BL-FIN-004 | Package สองคนบันทึกค่าหมอแยกตามผู้รับบริการได้โดย Admin ไม่ใช้สูตรตายตัว |
| BL-ANL-001 | Dashboard ใช้เฉพาะ `COMPLETED` และ `RECORDED` ที่ไม่ถูกยกเลิก แสดงรายได้ บริการยอดนิยม ช่วงเวลานัด/ให้บริการจริง และผลงานหมอนวดตามช่วงวันที่ |
| BL-ANL-002 | Insight เฉพาะ `ADMIN` ต้อง Filter รายละเอียดฝั่ง Server, แบ่งมุมมอง Revenue/Service/Therapist/Booking และ Export CSV ตาม Filter โดยไม่รวมข้อมูลสุขภาพหรือเบอร์เต็ม พร้อม Audit ทุกครั้ง |
| BL-PRI-001 | รายละเอียดสุขภาพเปิดดูได้เฉพาะใน Admin System ที่มีสิทธิ์และ Registered Admin LINE Group ที่ควบคุมสมาชิกตามหน้าที่งาน พร้อม Audit การเปิดเผยโดยไม่บันทึกรายละเอียดซ้ำ |
| BL-PRI-002 | Health Profile ใช้ข้าม Visit ได้ แต่ทุก Booking ต้องมี Health Snapshot และการแก้ไข/merge ต้อง Audit |
| BL-PRI-003 | Booking acknowledgement และ Explicit Health Consent ต้องแยก checkbox, ไม่ pre-check และเก็บหลักฐานแบบ versioned ต่อ Participant |
| BL-CAT-001 | Initial catalog ต้องมี 11 Service ตามหัวข้อ 7.1 รวม Couple Package แบบ `PER_BOOKING` สำหรับ 2 คนและ Hot Compress แบบจองเดี่ยว |

### 19.1 Phase 1.5 — My Bookings แบบ Read-only

- ลูกค้าที่ผ่าน LINE Login สามารถเปิด `/my-bookings` เพื่อดูเฉพาะ Booking ที่เชื่อมกับ LINE identity เดียวกัน
- แบ่งเป็น `กำลังจะมาถึง` สำหรับ `PENDING`/`CONFIRMED` ที่เวลานัดยังไม่ผ่าน และ `IN_SERVICE`; `ประวัติ` รวมสถานะสิ้นสุดทั้งหมด รวมถึง `PENDING`/`CONFIRMED` ที่เวลานัดผ่านแล้ว เพื่อไม่ให้ข้อมูลค้างจากงานปฏิบัติการแสดงเป็นนัดหมายอนาคต
- หน้าแสดงเฉพาะ Booking ID, สถานะ, วันเวลา, Service snapshot, Pax และราคาประเมินรวม ไม่แสดงเบอร์โทร ข้อมูลสุขภาพ พนักงาน หรือ Internal ID
- Booking จาก Guest Website จะปรากฏหลังลูกค้าเชื่อมด้วย Secure Status Link ที่ถูกต้องแล้วเท่านั้น ห้ามค้นหรือเปิดเผยรายการจากเบอร์โทรเพียงอย่างเดียว
- รอบนี้เป็น Read-only; ลูกค้ายังไม่สามารถ Reschedule หรือ Cancel เองและต้องติดต่อร้าน
- `/status` ยังคงเป็น Bearer Link สำหรับ Booking เดียวและไม่เปลี่ยนเป็นหน้าบัญชีลูกค้า

### 19.2 Admin Financial Allocation และ Dashboard

- หลัง Booking เป็น `COMPLETED` หรือ `RECORDED` เฉพาะ `ADMIN` เปิดหน้าต่างแบ่งรายได้ได้ การไม่กรอกทันทีไม่ขวางการจบบริการ แต่ Dashboard ต้องนับเป็นรายการรอจัดสรร
- Admin กรอกค่าหมอเป็นเงินบาทเต็มจำนวนแยกตาม Participant หมอนวดหนึ่งคนรับหลาย Participant ได้ และ Package สองคนเลือกหมอนวด/จำนวนเงินต่างกันได้
- ส่วนลดลดเฉพาะรายได้สุทธิของร้าน ไม่เปลี่ยนค่าหมอที่ Admin กรอก ระบบแสดงคำเตือนเมื่อค่าหมอรวมสูงกว่ารายได้ค่าบริการสุทธิ แต่อนุญาตให้บันทึกพร้อม Audit ได้
- ทิปที่รับจริงแบ่งให้หมอนวดแต่ละคนได้ ยอดคงเหลือเป็นของร้านโดยอัตโนมัติ ผลรวมส่วนแบ่งหมอนวดต้องไม่เกินยอดทิป
- เมื่อยอดทิปจาก Payment เปลี่ยนหลังเคยแบ่ง ระบบทำเครื่องหมายให้จัดสรรทิปใหม่ และไม่นำ Settlement เก่าที่ไม่ตรงยอดมาสรุป
- `RECORDED` ใช้กฎเดียวกัน แม้ไม่มี Therapist Assignment เดิม Admin สามารถเลือกหมอนวดภายหลังได้ การยกเลิกย้อนหลังต้องตัดออกจาก Dashboard
- Dashboard เรียงข้อมูลตามช่วงวันที่และแยกยอดบริการ, ทิป, เงินรับจริงที่ตรวจสอบแล้ว, ยอดค้างชำระ, ค่าหมอ, ส่วนทิปหมอ และส่วนของร้านอย่างชัดเจน
- ชั่วโมงยอดนิยมแสดงทั้งเวลานัดและเวลาเริ่มบริการจริง โดยข้อมูลเก่าที่ไม่เคยเก็บเวลาเริ่มจริงต้องไม่ถูกสมมติขึ้น

## 20. Phase 2 — CRM & Membership

รายการต่อไปนี้ถูกวางแผนไว้แต่ไม่เปิดใช้ใน Phase 1:

- Customer Membership
- Visit Counter โดยนับจาก Booking ที่ `COMPLETED` เท่านั้น
- สิทธิพิเศษเมื่อครบจำนวนครั้งที่กำหนด เช่น ครบ 10 ครั้ง
- เก็บวันเกิดโดยได้รับความยินยอม
- Birthday Voucher และการส่งสิทธิ์ในเดือนเกิดอัตโนมัติ
- Customer Directory และ Visit History เชิง CRM
- Loyalty Tier และ Campaign
- Customer Self-service Reschedule และ Cancel (My Bookings แบบ Read-only เปิดใช้ใน Phase 1.5 แล้ว)

รายละเอียด Phase 2 ต้องมี Business Logic และการอนุมัติแยกก่อนพัฒนา

## 21. ข้อมูล Operational ที่ใส่ภายหลังได้

รายการต่อไปนี้ไม่เป็น Blocker ต่อ HLD แต่ต้องกำหนดก่อน UAT/Production:

- ชื่อสาขาที่ใช้จริง ที่อยู่ เบอร์โทร และ URL แผนที่
- วันหยุดและข้อยกเว้นจากเวลาเริ่มต้น `10:00–22:00`
- รายการห้อง/เตียงและ Capacity เริ่มต้น
- Resource compatibility และ Active State ของ Initial Service Catalog
- Buffer time ระหว่างบริการ
- URL และเนื้อหาเต็มของ Privacy Notice/Booking Terms ที่สอดคล้องกับ Consent Baseline
- การอนุมัติ Proposed Health Retention 3 ปี หรือระยะเวลาอื่นพร้อมเหตุผลและขั้นตอนลบ/ถอนความยินยอม
- Cancellation wording และเหตุผลมาตรฐาน
- LINE Provider/Channel/Group identifiers ของ Production
- รายชื่อและสิทธิ์ผู้ใช้ Admin Web
- CAPTCHA Provider/Policy และ Challenge Threshold
- Rate Limit Window ต่อ IP/เบอร์โทรศัพท์ และจำนวน Active `PENDING` สูงสุดต่อเบอร์
- อายุ การเพิกถอน และขั้นตอนออก Secure Status Link ใหม่
- นโยบาย Block/Unblock เบอร์โทรศัพท์และคำอธิบายต่อผู้ใช้

## 22. เอกสารอ้างอิง

### Internal UX/UI References

- [Customer Design](./DESING/Side-Customer/DESIGN.md)
- [Customer Stitch Flow](./DESING/Side-Customer/FLOW_STITCH.md)
- [Admin Design](./DESING/Side-Admin/DESIGN.md)
- [Admin Stitch Flow](./DESING/Side-Admin/FLOW_STITCH.md)

### LINE Platform Constraints

- [LINE Messaging API — Group chats](https://developers.line.biz/en/docs/messaging-api/group-chats/)
- [LINE Messaging API — Webhook events and actions](https://developers.line.biz/en/reference/messaging-api/nojs/)
- [LINE Messaging API — User IDs](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)
- [LINE Login — Provider and channel linkage](https://developers.line.biz/en/docs/line-login/getting-started/)
- [LIFF — Using user profile information](https://developers.line.biz/en/docs/liff/using-user-profile/)
- [LINE Messaging API — Linking user accounts](https://developers.line.biz/en/docs/messaging-api/linking-accounts/)
- [LINE Messaging API — Receiving webhook events](https://developers.line.biz/en/docs/messaging-api/receiving-messages/)

### Privacy and Data Protection Guidance

- [Personal Data Protection Act B.E. 2562 — Royal Gazette](https://www.ratchakitcha.soc.go.th/DATA/PDF/2562/A/069/T_0052.PDF)
- [GPPC/PDPC Privacy Policy — retention and data-subject rights](https://gppc.pdpc.or.th/privacy-policy/)

เอกสารอ้างอิงนี้ใช้กำหนด technical/privacy controls เบื้องต้น ไม่แทนคำปรึกษากฎหมายหรือการตรวจทาน Privacy Notice ของร้าน
