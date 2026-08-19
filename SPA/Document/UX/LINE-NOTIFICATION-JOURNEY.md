# SPA 49 — LINE Notification UX & Journey

| รายการ | ค่า |
| --- | --- |
| ขอบเขต | Customer LINE OA และ Registered Admin LINE Group |
| ระยะ | Phase 1 |
| ผู้ใช้หลัก | ลูกค้าที่เชื่อม LINE และพนักงานผู้มีสิทธิ์ใน Admin Group |
| เป้าหมาย | ทำให้คำขอจองได้รับการรับทราบ ตรวจสอบ และยืนยันได้เร็ว โดยไม่ทำให้ผู้ใช้เข้าใจผิดเรื่องสถานะ |

เอกสารนี้กำหนดประสบการณ์ผู้ใช้บน LINE เท่านั้น ส่วนการติดตามและแก้ไข Notification Failure ใน Admin Web อยู่ที่ [ADMIN-WEB-OPERATIONS-JOURNEY.md](./ADMIN-WEB-OPERATIONS-JOURNEY.md)

## 1. หลักการ UX

1. ต้องแยกคำว่า **“รับคำขอแล้ว”** ออกจาก **“ยืนยันการจองแล้ว”** อย่างชัดเจนเสมอ
2. Booking ID, วัน-เวลา และสถานะเป็นข้อมูลที่ต้องมองเห็นก่อนรายละเอียดรอง
3. Admin Group ต้องตัดสินใจได้จาก Flex Message โดยไม่จำเป็นต้องเปิด Admin Web ในกรณีปกติ
4. Customer LINE ห้ามแสดง Health Declaration ไม่ว่ากรณีใด
5. การส่ง LINE ล้มเหลวต้องไม่ rollback Booking หรือ Capacity
6. ข้อความซ้ำจาก retry ต้องไม่ทำให้สถานะ Booking เปลี่ยนซ้ำ

## 2. Actors และขอบเขตช่องทาง

| Actor / Channel | สิ่งที่เห็น | สิ่งที่ทำได้ |
| --- | --- | --- |
| LINE-linked Customer ผ่าน Customer OA | สถานะและสรุป Booking ที่ปลอดภัยสำหรับลูกค้า | อ่าน Pending/Confirmed message, เปิดแผนที่, ติดต่อร้าน |
| Website Guest ที่ยังไม่เชื่อม LINE | ไม่ได้รับ LINE Notification | ติดตามผ่าน Secure Status Link และเลือกเชื่อม LINE ภายหลัง |
| สมาชิก Registered Admin LINE Group | ข้อมูล Booking, เบอร์โทร และ Health Declaration แยกผู้รับบริการ | โทรหาลูกค้าและ Confirm Booking ที่ยังเป็น `PENDING` |
| Group อื่นหรือผู้ใช้ที่ระบุตัวไม่ได้ | ต้องไม่ได้รับข้อมูลสุขภาพและไม่มีสิทธิ์ยืนยัน | ไม่มีสิทธิ์เปลี่ยนสถานะ |

สิทธิ์ใน LINE Admin Group แยกจาก Role `ADMIN`/`STAFF` ของ Admin Web และไม่ให้สิทธิ์เข้า Admin Web โดยอัตโนมัติ

## 3. End-to-end journey

```text
ลูกค้าส่งคำขอจอง
  ├─ หน้า Booking แสดง Booking ID + PENDING ทันที
  ├─ ถ้าเชื่อม LINE → Customer OA ส่ง “รับคำขอแล้ว”
  └─ Notification Worker → Admin Group ส่ง New Booking Flex
                              │
                              ├─ โทรตรวจสอบลูกค้า (ถ้าจำเป็น)
                              └─ กด “ยืนยันการจอง”
                                      │
                                      ├─ Booking: PENDING → CONFIRMED แบบ atomic
                                      ├─ Admin Group ได้ข้อความผลการยืนยัน
                                      └─ Customer OA ส่ง Confirmation Flex
```

### Journey map

| Stage | ผู้ใช้ | เป้าหมาย/คำถาม | Touchpoint | UX response ที่ต้องการ | Failure recovery |
| --- | --- | --- | --- | --- | --- |
| 1. Submit | ลูกค้า | “ร้านได้รับคำขอหรือยัง?” | Booking Web/LIFF | แสดง Booking ID และ `รอยืนยัน` ทันที | ถ้าสร้าง Booking ไม่สำเร็จ ห้ามแสดงเลขจองหรือกัน Capacity |
| 2. Acknowledge | ลูกค้าที่เชื่อม LINE | “ตอนนี้ถือว่าจองสำเร็จแล้วหรือยัง?” | Customer OA Pending Flex | ใช้คำว่า “รับคำขอแล้ว — ยังไม่ยืนยัน” พร้อมวัน เวลา และบริการ | ถ้าส่งไม่ได้ Booking ยัง `PENDING`; ลูกค้าติดตาม Secure Status Link ได้ |
| 3. Review | พนักงานใน Group | “ใคร จองอะไร เมื่อไร มีข้อควรระวังหรือไม่?” | Admin New Booking Flex | จัดลำดับ Booking ID/สถานะ → นัดหมาย → ผู้รับบริการ → Health Alert → actions | ถ้าส่ง Group ไม่ได้ Booking ยังอยู่ Pending Queue ใน Admin Web |
| 4. Decide | พนักงานใน Group | “ยืนยันรายการนี้ได้หรือไม่?” | ปุ่ม Confirm / โทรหาลูกค้า | ปุ่มหลัก Confirm และปุ่มรองโทร; คำสั่งต้องมี Booking ID | ถ้าระบุตัวผู้กดหรือ Group ไม่ได้ ระบบปฏิเสธและให้ใช้ Admin Web |
| 5. Group feedback | ผู้ปฏิบัติงานทุกคน | “มีใครจัดการแล้วหรือยัง?” | Admin Group Result Flex | แสดง Booking ID, สถานะล่าสุด, ผู้ยืนยัน และเวลา | หากกดซ้ำ ให้ตอบสถานะล่าสุดโดยไม่เปลี่ยนข้อมูลซ้ำ |
| 6. Confirmed | ลูกค้า | “นัดของฉันยืนยันแล้ว ต้องทำอะไรต่อ?” | Customer OA Confirmation Flex | แสดงรายละเอียดนัด ราคาโดยประมาณ คำแนะนำและแผนที่ | หากส่งไม่ได้ Admin Web ต้องชี้ว่าควรติดต่อลูกค้าทางโทรศัพท์ |

## 4. Message specification — Admin LINE Group

### 4.1 New Booking Flex

ลำดับข้อมูลจากบนลงล่าง:

1. Header: `มีรายการจองใหม่` และสถานะ `รอการยืนยัน`
2. Booking ID เพื่อใช้อ้างอิงระหว่างช่องทาง
3. วันและเวลา โดยใช้ timezone `Asia/Bangkok`
4. ชื่อผู้ติดต่อและเบอร์โทรศัพท์
5. รายชื่อผู้รับบริการแต่ละคน พร้อม Service และ Duration
6. จำนวนผู้รับบริการ
7. Health Declaration แยกตามชื่อเล่น เฉพาะเมื่อมีข้อมูล
8. Action รอง: `โทรหาลูกค้า`
9. Action หลัก: `ยืนยันการจอง`

แนวทาง visual hierarchy:

- Forest Green ใช้กับ header/action หลัก; Amber ใช้กับ `PENDING`
- Health Alert ใช้พื้นแดงอ่อน + icon + label ห้ามใช้สีอย่างเดียว
- เนื้อหาที่ต้องตัดสินใจต้องอ่านได้โดยไม่กด “ดูเพิ่มเติม”
- เบอร์โทรต้องเป็น `tel:` action และ Booking ID ต้องไม่ซ่อน

ตัวอย่าง microcopy:

```text
มีรายการจองใหม่
#BK-20260819-001 · รอการยืนยัน

พุธ 19 ส.ค. 2569 · 14:30 น.
ผู้ติดต่อ: คุณเอ · 08x-xxx-xxxx

คุณเอ — นวดแผนไทย 90 นาที
คุณบี — นวดน้ำมัน 60 นาที

ข้อมูลสุขภาพสำหรับเตรียมบริการ
คุณเอ: [ข้อความที่ลูกค้าแจ้ง]

[โทรหาลูกค้า] [ยืนยันการจอง]
```

### 4.2 Confirm interaction

- ปุ่มใช้ LINE message action ส่งคำสั่งที่ระบบรองรับพร้อม Public Booking ID
- Webhook ต้องตรวจ signature, Registered Group ID และ LINE User ID ของผู้กด
- Confirm ได้เฉพาะ `PENDING`; ผู้กดคนแรกสำเร็จเพียงคนเดียว
- ระหว่างประมวลผล ผู้ใช้เห็นข้อความคำสั่งใน Group ซึ่งทำหน้าที่เป็นหลักฐานการกระทำ
- Result message ต้องแสดงอย่างน้อย `Booking ID`, `ยืนยันแล้ว`, ผู้ยืนยัน และเวลายืนยัน

### 4.3 Duplicate / stale action

หาก Booking ถูกยืนยันหรือดำเนินการไปแล้ว:

```text
#BK-20260819-001 ดำเนินการแล้ว
สถานะปัจจุบัน: ยืนยันแล้ว
ไม่มีการเปลี่ยนสถานะซ้ำ
```

หาก Event ไม่มาจาก Registered Group หรือไม่มี User ID ระบบต้องไม่เปิดเผยรายละเอียดเพิ่ม และแนะนำให้ดำเนินการผ่าน Admin Web

## 5. Message specification — Customer LINE OA

### 5.1 Pending acknowledgement

Primary message: `รับคำขอจองแล้ว — กรุณารอร้านยืนยัน`

ต้องมี:

- Booking ID
- สถานะ `รอยืนยัน`
- วัน เวลา Service/Duration และจำนวนผู้รับบริการ
- ข้อความชัดเจนว่าคำขอยังไม่ใช่การยืนยัน
- ช่องทางติดต่อร้าน

ห้ามมี Health Declaration, หมอนวด, internal ID, task/error detail หรือข้อมูลของ Admin approver

### 5.2 Confirmation Flex

Primary message: `ยืนยันการจองเรียบร้อยแล้ว`

ต้องมี:

- Booking ID และชื่อลูกค้า
- วัน เวลา Service/Duration และจำนวนผู้รับบริการ
- ราคาประเมินรวม พร้อมระบุว่าชำระที่ร้าน
- คำแนะนำก่อนเข้ารับบริการ
- วิธีติดต่อหากต้องการเปลี่ยนแปลงหรือยกเลิก
- ปุ่มเปิดแผนที่ร้านเมื่อมี URL ที่ผ่าน validation

### 5.3 Changed / cancelled Booking

เป็น requirement ของ Phase 1 แต่ควรใช้ template แยกเพื่อไม่ให้สับสนกับ Confirmation:

- `รายละเอียดการจองมีการเปลี่ยนแปลง` — แสดงค่าปัจจุบันและช่องทางติดต่อร้าน
- `การจองถูกยกเลิก` — แสดง Booking ID, เหตุผลที่เหมาะสมต่อการเปิดเผย และช่องทางติดต่อ

## 6. Delivery states และประสบการณ์ผู้ใช้

| Outbox state | ความหมายเชิงระบบ | สิ่งที่ผู้ใช้ LINE เห็น | การจัดการ |
| --- | --- | --- | --- |
| `PENDING` | รอสร้าง Cloud Task | ยังไม่เห็นข้อความ | ระบบ reconcile อัตโนมัติ |
| `ENQUEUED` | อยู่ใน Cloud Tasks | ยังไม่เห็นข้อความ | รอ dispatch |
| `PROCESSING` | Worker กำลังส่ง | ยังไม่ควรแสดงว่าสำเร็จ | ใช้ processing lease ป้องกันงานซ้ำ |
| `RETRYABLE` | ส่งชั่วคราวไม่สำเร็จ | อาจยังไม่เห็นข้อความ | ระบบ retry อัตโนมัติตาม backoff |
| `SENT` | LINE รับคำขอส่งแล้ว | ได้รับข้อความตามปกติ | ไม่มี action เพิ่ม |
| `FAILED` | ล้มเหลวถาวรหรือเกิน retry budget | ไม่ได้รับข้อความ | Admin Web แจ้งให้ retry หรือติดต่อทางโทรศัพท์ |

การส่งสำเร็จหมายถึง provider รับข้อความแล้ว ไม่ควรตีความว่า user อ่านข้อความแล้ว

## 7. Privacy และ operational safety

- Health details แสดงได้เฉพาะ Registered Admin Group และ Admin Web ที่มีสิทธิ์
- ห้ามใส่ Health details ใน Customer LINE, Group อื่น, Cloud Task payload, URL, log, metric หรือ audit body
- Operational Alert จาก Cloud Monitoring ต้องเป็น privacy-safe และไม่ใช้ template เดียวกับ New Booking Flex
- ห้ามใช้ public confirm URL ที่ส่งต่อได้; Confirmation ต้องผ่าน signed webhook และ identity ของ Group member
- ผู้ดูแลร้านต้องทบทวนสมาชิก Group และถอดผู้พ้นหน้าที่ทันที

## 8. Content and accessibility checklist

- ใช้ภาษาไทยเป็นค่าเริ่มต้นและรองรับข้อความยาวโดยไม่ตัดชื่อบริการ/ข้อมูลสุขภาพ
- วัน เวลา และราคาใช้รูปแบบเดียวกันทุก message
- Icon เป็นตัวช่วยเท่านั้น ต้องมี text label กำกับสถานะ
- `altText` ของ Flex ต้องสื่อ Booking ID และเหตุการณ์โดยไม่รวมข้อมูลสุขภาพ
- CTA label ต้องเป็นคำกริยาที่ชัดเจนและไม่เกินพื้นที่ที่ LINE รองรับ
- ทดสอบบน LINE iOS/Android ทั้ง font scaling ปกติและขนาดใหญ่

## 9. Acceptance criteria

1. Customer Pending และ Confirmed message ใช้คำต่างกันชัดเจน และไม่มี Health details
2. Admin New Booking Flex แสดงข้อมูลครบสำหรับ Booking 1 และ 2 คน รวมบริการต่างระยะเวลา
3. Health details ปรากฏเฉพาะ Registered Admin Group และมี audit การเปิดเผยโดยไม่คัดลอกข้อความลง audit
4. การกด Confirm พร้อมกันหลายคนเปลี่ยนสถานะได้ครั้งเดียว และ Group ได้รับสถานะล่าสุด
5. Booking ยังคงสถานะเดิมเมื่อ LINE delivery ล้มเหลว
6. `RETRYABLE` ถูก retry อัตโนมัติ; `FAILED` ปรากฏใน Admin Web พร้อม recovery action
7. Guest ที่ไม่เชื่อม LINE ยังจองและติดตามผ่าน Secure Status Link ได้

## 10. Current implementation gaps / recommendations

| Priority | Gap ที่พบจากโค้ดปัจจุบัน | ผลกระทบ | Recommendation |
| --- | --- | --- | --- |
| P0 | Admin confirmation result Flex แสดง Booking/ลูกค้า/เวลา แต่ยังไม่แสดงชื่อผู้ยืนยันและเวลาที่กดยืนยันตาม Business Logic | คนใน Group ตรวจ ownership ไม่ครบ | เพิ่ม safe approver display และ confirmed timestamp จาก audit/result projection |
| P0 | Customer changed/cancelled templates ยังไม่เห็นเป็น template เฉพาะใน Worker | ลูกค้าอาจไม่ได้ข้อความที่สื่อเหตุการณ์ตรง | เพิ่ม versioned templates และ test ว่าไม่มี health data |
| P1 | Customer Pending Flex ปัจจุบันยังไม่มีช่องทางติดต่อร้าน | Recovery path ไม่ครบ | เพิ่มโทร/LINE contact ที่มาจาก branch config |
| P1 | Admin Group success message ยังไม่เปิด Admin Booking deep link | งานต่อเนื่อง เช่น assign therapist ต้องค้นหาเอง | เพิ่ม authenticated Admin URL เฉพาะเมื่อ contract/route พร้อม; URL ห้ามมีข้อมูลสุขภาพ/token |
| P1 | ข้อความยืนยันมีคำแนะนำ “แจ้งล่วงหน้า 1 วัน” ซึ่งต้องยืนยันเป็น policy ก่อนใช้ Production | อาจสื่อกฎที่ธุรกิจยังไม่อนุมัติ | ย้าย wording ไป branch configuration หรืออนุมัติเป็น Business Rule |

## 11. Sources of truth

- [BusinessLogic.md](../BusinessLogic.md) — Booking, LINE, privacy และ failure rules
- [TDD.md](../TDD.md) — LINE integration, outbox และ Cloud Tasks
- [LLD.md](../LLD.md) — template/data contracts และ worker behavior
- [Admin DESIGN.md](../DESING/Side-Admin/DESIGN.md) — brand/status visual language
