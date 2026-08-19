# SPA 49 — Admin Web Operations UX & Journey

| รายการ | ค่า |
| --- | --- |
| Surface | SPA Admin Web — desktop-first |
| ผู้ใช้หลัก | Reception / `STAFF` และ Branch Manager / `ADMIN` |
| งานหลัก | ตรวจ Booking ใหม่, ยืนยัน, มอบหมายหมอนวด, เปลี่ยนสถานะ และแก้ Notification Failure |
| Primary visual anchor | Pending Booking Queue และรายการที่ต้องดำเนินการตามเวลา |

เอกสารนี้กำหนด operational journey ของ Admin Web โดยเชื่อมกับ LINE flow ใน [LINE-NOTIFICATION-JOURNEY.md](./LINE-NOTIFICATION-JOURNEY.md)

## 1. UX goals

1. พนักงานต้องเห็น Booking ที่เสี่ยงตกหล่นก่อนข้อมูลเชิงสถิติ
2. การยืนยัน Booking ต้องทำได้เร็ว แต่ยังเห็นวัน เวลา Service, Pax และ Health Alert ก่อนตัดสินใจ
3. สถานะระบบส่ง LINE ต้องแยกจากสถานะ Booking เพื่อไม่ให้เข้าใจว่า “ส่งข้อความไม่สำเร็จ = Booking ไม่สำเร็จ”
4. หน้า Notification ต้องบอกว่าเหตุการณ์ใดระบบกำลัง retry และเหตุการณ์ใดต้องให้พนักงานลงมือ
5. ทุก action สำคัญต้องมี feedback, conflict recovery และ audit trail

## 2. Roles and permissions

| Capability | `ADMIN` | `STAFF` |
| --- | :---: | :---: |
| ดู/แก้ไข/Confirm/Cancel Booking | ✓ | ✓ |
| เปลี่ยนสถานะการให้บริการและมอบหมายหมอนวด | ✓ | ✓ |
| ดู Health details สำหรับปฏิบัติงาน | ✓ | ✓ |
| ดู Notification delivery และ retry | ✓ | ✓ |
| จัดการผู้ใช้ Role, security และ LINE Group configuration | ✓ | — |

การเป็นสมาชิก LINE Admin Group ไม่ได้ให้สิทธิ์เข้า Admin Web และ Role ใน Admin Web ไม่ควรถูกใช้แทนการควบคุมสมาชิก Group

## 3. Primary staff journey

```text
Sign in
  → Dashboard แสดง Pending / Unassigned / Notification Failed
  → เปิด Pending Booking
  → ตรวจวัน-เวลา + Service/Pax + Health Alert
  → โทรหาลูกค้าหากต้องตรวจสอบเพิ่ม
  → Confirm หรือ Cancel พร้อมเหตุผล
  → มอบหมายหมอนวดก่อนเวลาให้บริการ
  → Start service
  → Complete / No-show

Notification delivery ทำงานขนาน:
  Booking event → Outbox/Cloud Tasks → LINE
                              └─ FAILED → Admin Notification Queue → Retry/โทรติดตาม
```

### Journey map

| Stage | Staff goal | Screen / touchpoint | Information hierarchy | Primary action | Recovery |
| --- | --- | --- | --- | --- | --- |
| 1. Orient | รู้ว่างานเร่งด่วนมีอะไร | Dashboard | Pending ตามเวลานัด → Unassigned → Failed delivery | เปิด Queue ที่ต้องจัดการ | หากโหลด count ไม่ได้ ให้คงค่าล่าสุดพร้อมสถานะ stale |
| 2. Review | ตรวจว่ารับ Booking ได้ | Booking list + detail drawer | สถานะ/เวลา → ลูกค้า → Service/Pax → Capacity → Health Alert | Confirm | หากข้อมูล version เก่า ให้ refresh และแสดงค่าปัจจุบัน |
| 3. Decide | รับหรือปฏิเสธคำขอ | Confirmation dialog | Booking ID, ผลของ action และ warning ที่เกี่ยวข้อง | ยืนยัน action | Cancel ต้องบังคับเหตุผล; validation ต้องรักษาข้อมูลที่กรอก |
| 4. Prepare | เตรียมห้อง/หมอนวด/ข้อมูลสุขภาพ | Calendar + assignment | เวลา, duration, participant, therapist, warning | Assign therapist | ห้าม Start จนมอบหมายครบทุก participant |
| 5. Serve | อัปเดตสถานะตามหน้างาน | Booking drawer | สถานะปัจจุบันและ valid next action | Start / Complete / No-show | Invalid transition แสดงเหตุผลและ state ล่าสุด |
| 6. Monitor delivery | รู้ว่าลูกค้า/Group ได้รับ LINE หรือไม่ | Notifications | Destination/event → Booking ID → state → เวลา → attempt/error | Retry เฉพาะ `FAILED` | หาก retry ไม่ได้ ให้แสดง error และช่องทางโทรติดตาม |

## 4. Information architecture

### 4.1 Global navigation

รายการหลัก Phase 1:

- รายการจอง
- ปฏิทิน
- สล็อตและความจุ
- บริการและราคา
- หมอนวด
- การแจ้งเตือน

Notification badge ต้องหมายถึง **จำนวนรายการที่ต้องให้คนดำเนินการ** ไม่ใช่จำนวน event ทั้งหมดหรือ event ที่ระบบกำลัง retry อัตโนมัติ

### 4.2 Dashboard priority

เรียงตามความเร่งด่วน:

1. Pending Booking ที่ใกล้เวลานัดที่สุด
2. Confirmed Booking ที่ยังไม่มอบหมายหมอนวด
3. Notification `FAILED` ที่ต้อง retry หรือติดต่อทางโทรศัพท์
4. Booking วันนี้ตามลำดับเวลา

Metric หรือ analytics ไม่ควรแย่ง visual weight จาก operational queue

## 5. Booking detail UX

Detail drawer ควรรักษา context ของรายการเดิมและมีส่วนดังนี้:

1. Booking ID, status และ appointment time
2. Customer contact และ source (`LINE` / `Guest Web`)
3. Participant cards เฉพาะเมื่อช่วยแยกข้อมูลของ 2 คน ไม่ควรสร้าง nested card เกินจำเป็น
4. Service, Duration, Pax และราคาประเมิน
5. Health Alert แบบ collapsed-by-default พร้อม action “เปิดดูข้อมูลสุขภาพ” และ audit เมื่อเปิด
6. Therapist assignment
7. Valid next actions ตาม state

Action priority:

| Current state | Primary | Secondary / destructive |
| --- | --- | --- |
| `PENDING` | Confirm | โทรหาลูกค้า, Cancel พร้อมเหตุผล |
| `CONFIRMED` | Assign therapist / Start เมื่อครบ | แก้ไข, Cancel, No-show เมื่อถึงเงื่อนไข |
| `IN_SERVICE` | Complete | ไม่มี transition ย้อนกลับใน flow ปกติ |
| Terminal | ไม่มี | แสดง audit/history เท่านั้น |

## 6. Notification Center specification

### 6.1 Primary task

ตอบคำถามให้ได้ภายในหนึ่งหน้าจอ:

- ข้อความอะไร ส่งไปช่องทางไหน สำหรับ Booking ใด
- สำเร็จหรือยัง
- ถ้ายังไม่สำเร็จ ระบบกำลัง retry หรือพนักงานต้องทำอะไร
- ลูกค้าต้องได้รับการติดต่อทางโทรศัพท์หรือไม่

### 6.2 Recommended layout

Desktop ใช้ data table หรือ compact record list ที่มี column ต่อไปนี้:

| Column | Content |
| --- | --- |
| Created | วันเวลา `Asia/Bangkok` พร้อม relative age แบบรอง |
| Event | ชื่อที่อ่านได้ เช่น “แจ้งคำขอใหม่ไป Admin Group” |
| Destination | Customer LINE / Admin Group / Operational Alert |
| Booking | Public Booking ID ที่เปิด detail drawer ได้ |
| Delivery status | Status label + icon; ไม่ใช้สีอย่างเดียว |
| Attempts | จำนวนครั้ง และ next retry เมื่อมี |
| Last error | Safe error label ไม่แสดง provider body/secret |
| Action | Retry, เปิด Booking, โทรหาลูกค้าตามเงื่อนไข |

Filters:

- `ต้องดำเนินการ` — `FAILED` เท่านั้น
- `ระบบกำลังส่ง` — `PENDING`, `ENQUEUED`, `PROCESSING`, `RETRYABLE`
- `ส่งสำเร็จ` — `SENT`
- Destination และช่วงเวลา

### 6.3 State semantics

| State | User-facing label | Tone | Human action |
| --- | --- | --- | --- |
| `PENDING` | รอสร้างคิว | Neutral/amber | ไม่มี; ระบบจัดการ |
| `ENQUEUED` | เข้าคิวแล้ว | Neutral/amber | ไม่มี |
| `PROCESSING` | กำลังส่ง | Blue | ไม่มี |
| `RETRYABLE` | ระบบจะลองส่งใหม่ | Amber | เฝ้าดู; ไม่ควรนับเป็นงาน manual ทันที |
| `SENT` | ส่งสำเร็จ | Green | ไม่มี |
| `FAILED` | ส่งไม่สำเร็จ — ต้องตรวจสอบ | Red | Retry หรือใช้ fallback channel |

`RETRYABLE` จะเปลี่ยนเป็น `FAILED` เมื่อเกิน attempt/time budget ดังนั้น badge “ต้องตรวจสอบ” ไม่ควรรวม `RETRYABLE` เว้นแต่มี business threshold สำหรับ stale retry ที่กำหนดไว้อย่างชัดเจน

### 6.4 Retry journey

1. Staff เปิด filter `ต้องดำเนินการ`
2. ตรวจ Booking, destination, attempt count, last safe error และเวลาที่ล้มเหลว
3. หากเป็น Customer LINE ให้เห็น CTA `เปิด Booking` และ `โทรหาลูกค้า`
4. กด `ส่งเข้าคิวใหม่`
5. UI disable action ระหว่าง request และประกาศสถานะผ่าน accessible live region
6. เมื่อ API สำเร็จ เปลี่ยน label เป็น `รอส่งใหม่` พร้อมเวลาล่าสุด โดยไม่อ้างว่าส่งสำเร็จ
7. Refresh/poll จนเป็น `SENT` หรือกลับเป็น `FAILED`

Retry เป็นการขอ enqueue ใหม่ ไม่ใช่การส่งสำเร็จ ดังนั้น success toast ควรใช้คำว่า `ส่งเข้าคิวใหม่แล้ว` ไม่ใช่ `ส่งข้อความแล้ว`

### 6.5 Empty, loading and error states

| State | UX copy / behavior |
| --- | --- |
| Initial loading | Skeleton rows หรือข้อความ “กำลังโหลดสถานะการส่ง…”; รักษา layout ไม่ให้กระโดด |
| No events | “ยังไม่มีประวัติการแจ้งเตือน” |
| No action required | “ไม่มีรายการที่ต้องดำเนินการ” พร้อมเวลาที่ตรวจล่าสุด |
| List load failed | Error banner + `ลองใหม่`; ห้ามเปลี่ยน badge เป็น 0 เพราะอาจซ่อน incident เดิม |
| Retry request failed | Toast/banner ระบุว่า Booking ไม่เปลี่ยนสถานะ และให้ลองใหม่/โทรติดต่อลูกค้า |
| Unknown state | แสดง raw safe state เป็น Neutral และไม่เสนอ action ที่คาดเดาเอง |

## 7. Cross-channel consistency

| Concept | Admin Web | LINE Admin Group | Customer LINE |
| --- | --- | --- | --- |
| Booking reference | Public Booking ID | Public Booking ID | Public Booking ID |
| Pending | `รอยืนยัน` | `รอการยืนยัน` | `รับคำขอแล้ว — ยังไม่ยืนยัน` |
| Confirmed | `ยืนยันแล้ว` | Result message | `ยืนยันการจองเรียบร้อยแล้ว` |
| Health details | เปิดแบบ audited | แสดงเฉพาะ registered Group | ห้ามแสดง |
| Delivery failure | แสดง state/action | ไม่รับประกันว่าจะเห็น | ไม่รับประกันว่าจะเห็น; ใช้ status page/โทรศัพท์ |

## 8. Responsive and accessibility

- Admin เป็น desktop-first: validate ที่ 1280px, 1440×900 และ 1920×1080
- ที่ความกว้างต่ำ ให้คง Booking ID, status, appointment และ action ไว้ก่อน column รอง
- ทุก table/filter/action ใช้ keyboard ได้และมี visible focus
- Status ต้องมี text + icon/shape ไม่ใช้สีอย่างเดียว
- Drawer/dialog ต้อง trap focus, ปิดด้วย Escape และคืน focus ไปยัง trigger
- Toast และ asynchronous state change ใช้ `aria-live`; error ใช้ `role="alert"` ตามความเหมาะสม
- รองรับข้อความไทย/อังกฤษยาวโดยไม่ตัด Booking ID, Service, error หรือ action สำคัญ

## 9. Privacy and security UX

- Health details ไม่แสดงใน Notification list, toast, badge, URL หรือ client log
- การเปิด Health details ต้องทำจาก Booking detail ที่มีสิทธิ์และสร้าง audit event
- Error UI ห้ามแสดง LINE token, User ID, Group ID เต็ม, provider response body หรือ request payload
- Admin session refresh ต้องไม่ทำให้ form/action ที่กำลังดำเนินการสูญหายโดยไม่แจ้ง
- Permission denied ต้องแยกจาก system error และไม่เสนอ action ที่ผู้ใช้ไม่มีสิทธิ์

## 10. Acceptance criteria

1. หลัง Sign in พนักงานเห็น Pending, Unassigned และ Failed notification count โดยไม่ต้องค้นหาเอง
2. Booking detail แสดงข้อมูลที่ใช้ตัดสินใจก่อน Confirm และไม่เปิด Health details โดยไม่เกิด audit
3. Confirm/Cancel/Start/Complete/No-show แสดงเฉพาะ transition ที่ถูกต้อง
4. Notification badge นับเฉพาะรายการที่ต้องให้คนดำเนินการตามนิยามที่อนุมัติ
5. `RETRYABLE` สื่อว่าระบบกำลังลองใหม่; `FAILED` มี Retry และ fallback action
6. Retry success เปลี่ยนเป็น queued/retryable ไม่แสดงว่า LINE ส่งสำเร็จก่อน state เป็น `SENT`
7. List load error ไม่ล้าง count ที่ทราบล่าสุดเป็นศูนย์
8. ทุก flow ใช้ keyboard ได้ และสถานะ asynchronous ถูกประกาศแก่ screen reader
9. UI ไม่แสดง health/credential/provider-sensitive data ใน notification operations

## 11. Current implementation assessment

| Priority | Current behavior | UX issue | Recommended change |
| --- | --- | --- | --- |
| P0 | `notificationRequiresAction()` นับทั้ง `FAILED` และ `RETRYABLE` แต่ UI มีปุ่ม Retry เฉพาะ `FAILED` | Badge พาผู้ใช้ไปยังรายการที่ไม่มี manual action และสร้าง alert fatigue | เปลี่ยน manual-action count เป็น `FAILED`; เพิ่ม filter “ระบบกำลังส่ง” สำหรับ `RETRYABLE` |
| P0 | Notification row แสดง event type แบบ technical และไม่แสดง destination/created time/next retry | พนักงานตัดสินใจไม่ได้ว่าต้องโทรหาใครหรือรอระบบ | เพิ่ม human label, target, timestamps และ booking deep link จาก safe API projection |
| P1 | หน้า Notification โหลดครั้งเดียวเมื่อ mount ขณะที่ badge poll ทุก 30 วินาที | badge กับ list อาจไม่ตรงกัน | เพิ่ม polling เมื่อ tab visible หรือปุ่ม Refresh พร้อม “ตรวจล่าสุดเมื่อ…” |
| P1 | Retry ไม่มี per-row pending state | กดซ้ำได้และไม่เห็นว่าคำสั่งกำลังทำงาน | disable เฉพาะ row, show progress และป้องกัน duplicate request ฝั่ง UI |
| P1 | `FAILED` มี Retry แต่ไม่มี fallback action | Customer notification failure ยังต้องตามด้วยโทรศัพท์ | เพิ่ม `เปิด Booking` และ `โทรหาลูกค้า` เฉพาะ destination ที่เกี่ยวข้อง |
| P2 | รายการเป็น compact cards โดยข้อมูลเพิ่มในอนาคตจะสแกนยาก | density ไม่เหมาะกับ operational history จำนวนมาก | เปลี่ยนเป็น semantic table บน desktop พร้อม responsive row detail |

ข้อเสนอที่ต้องเพิ่ม field/API contract เช่น destination, next retry หรือ safe error description ต้องอนุมัติเป็น backend work แยกก่อน implementation; เอกสาร UX นี้ไม่เปลี่ยน contract ปัจจุบันเอง

## 12. Sources of truth

- [BusinessLogic.md](../BusinessLogic.md) — roles, Booking lifecycle, LINE และ failure rules
- [TDD.md](../TDD.md) — permissions, API, notification state machine และ retry policy
- [LLD.md](../LLD.md) — Firestore/outbox fields และ worker contracts
- [Admin DESIGN.md](../DESING/Side-Admin/DESIGN.md) — desktop design system
- [Admin FLOW_STITCH.md](../DESING/Side-Admin/FLOW_STITCH.md) — navigation and screen intent

