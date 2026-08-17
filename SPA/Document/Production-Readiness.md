# SPA49 Production Readiness Checklist

อัปเดตล่าสุด: 17 สิงหาคม 2026 — Environment: `the49-487609` / `asia-southeast1`

## Gate status

| Gate | สถานะ | หลักฐาน/งานที่เหลือ |
| --- | --- | --- |
| Test environment แยกจาก Production | PASS | `spa-test-db`, `spa-*-test`, Test queue/scheduler |
| Firestore protection | PASS | Delete protection, PITR, daily backup; Production 30 วัน / Test 7 วัน |
| Firestore indexes | PASS | Booking list/status/phone guard indexes `READY` ทั้งสอง database |
| API unit/lint | PASS | 24 tests, Ruff ผ่าน |
| Worker unit/lint | PASS | 5 tests, Ruff ผ่าน |
| Frontend lint/type/build | PASS | Admin/Customer ผ่าน; shared types 2 tests |
| Dependency audit | PASS | `npm audit --omit=dev`: 0 vulnerabilities |
| Responsive Customer UI | PASS | 360×800, 390×844, 430×932 ไม่มี horizontal overflow; tap targets ≥44px |
| Booking transaction | PASS | 15-minute buckets ตลอด duration, pax atomicity, idempotency replay และ duplicate guard |
| Secure status projection | PASS | ไม่คืน phone, health details หรือ internal IDs |
| Firebase Test authorized domain | PASS | Test Admin Cloud Run domain ถูกเพิ่มโดยรักษา domains เดิม |
| LINE webhook verification | PASS | Customer/Admin routes, raw-body HMAC-SHA256, endpoint-specific secrets, empty-event ACK และ dedupe deploy ใน Test แล้ว |
| Admin authentication | PASS | Popup sign-in ด้วย `chonlathan@manee-son.com`, Firebase session และ API ID token ผ่าน; fix รวมอยู่ใน revision ล่าสุด |
| Admin Phase 1 modules | PASS | Calendar, Capacity/Closure, Services/Prices, Therapists/Assignment และ Notifications เชื่อม Test API/Firestore แล้ว |
| Admin operations UAT | BLOCKED | Product Owner ต้องทดสอบ Confirm/Cancel/Assign/Start/Complete ด้วยข้อมูล Test |
| LINE test delivery | BLOCKED | Token valid (bot info 200), push ไป Group ID ได้ HTTP 400; ต้องเพิ่ม Bot ให้ถูกกลุ่ม/channel |
| Privacy/Terms legal review | BLOCKED | `/privacy` และ `/terms` เป็น Draft |
| LIFF/LINE customer linking | OPEN | ยังไม่ครบ Customer LINE identity/linking flow |
| reCAPTCHA/rate protection | OPEN | Phone/duplicate guards มีแล้ว; reCAPTCHA Enterprise ยังไม่เชื่อม |
| Automated browser suite | PASS | Playwright 6 scenarios ผ่านทั้ง desktop/mobile กับ Test Cloud URLs |
| Load/concurrency test | OPEN | ต้องรัน 20-session last-capacity test กับ Emulator/Test DB |
| Backup restore drill | OPEN | Backup schedule มีแล้ว แต่ยังไม่ได้ restore และจับเวลา RTO |
| Source traceability | BLOCKED | Product Owner ต้อง Commit เอง; Production scripts ปฏิเสธ dirty worktree โดย default |

## Production promotion rule

ห้าม deploy Production revision ใหม่หรือ seed Production capacity จนกว่า Blocked/Open gates
ทั้งหมดด้านบนจะปิด และ Test images ชุดเดียวกันผ่าน UAT จากนั้นจึง build immutable Production
images จาก clean committed source, seed `spa-db`, deploy Worker → API → Customer → Admin,
สร้าง Production Scheduler และทำ smoke test/rollback check

## External actions ที่ Product Owner ต้องทำ

1. เปิด Admin Test URL และทำ Admin operations UAT: Confirm/Cancel/Assign/Start/Complete
2. ตรวจว่า Admin Messaging API Bot ถูกเพิ่มใน LINE test group ที่ตรงกับ
   `spa-line-admin-group-id`; หลังแก้ให้ trigger `spa-outbox-reconcile-test`
3. ตรวจและอนุมัติข้อความ `/privacy` และ `/terms` หรือส่งฉบับ Legal ที่แก้แล้ว
4. Review และ Commit งานใน `SPA/` ด้วยตนเองตามข้อกำหนดว่า Codex ไม่ทำ Git operation

## Test deployment evidence

- API revision: `spa-api-test-00005-s7l`
- Admin revision: `spa-admin-web-test-00008-9nk`
- Notification Worker revision: `spa-notification-worker-test-00003-wm9`
- `/health/live` และ `/health/ready`: HTTP 200; Firestore `spa-test-db` ready
- Admin Web และ Customer Web: HTTP 200
- Cloud Run ERROR logs หลัง revision ชุดนี้: ไม่พบรายการ
- `npm run test:e2e`: 6 passed (desktop/mobile Chromium)

### Admin Phase 1 module deployment

- API revision: `spa-api-test-00007-wlz`
- Admin revision: `spa-admin-web-test-00011-zwb`
- Authenticated QA: Navigation ทั้ง 6 เมนูและข้อมูลจริงจาก `spa-test-db` ผ่าน
- Calendar: เวลาแสดงตาม `Asia/Bangkok`
- Capacity: 7 เตียง / เปิดใช้งาน 5 เตียง และ Special Closure พร้อมใช้งาน
- Service catalog: 11 services / 17 variants พร้อมแก้ราคาและ Active state
- Notification history: แสดง delivery state/error/attempt และขอ retry ได้
- Viewports: 1280×900, 1440×900, 1920×1080 ไม่มี horizontal overflow

### LINE webhook deployment

- API revision: `spa-api-test-00008-j6p`
- Customer: `POST /api/v1/webhooks/line/customer`
- Admin: `POST /api/v1/webhooks/line/admin`
- ไม่มี signature / signature ผิด: HTTP 401 (ไม่ใช่ 404)
- Signed verification ที่มี `events: []`: HTTP 200 ตาม automated tests
- Channel Secrets mount จาก Secret Manager แยก Customer/Admin
- Webhook event เก็บเฉพาะ safe processing metadata และ deduplicate ด้วย `webhookEventId`
