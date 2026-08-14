## สถานะสำคัญก่อนเริ่ม

  ตอนนี้ยังไม่สามารถรัน End-to-End Testing แบบครบวงจรได้ เพราะ implementation ปัจจุบันยังเป็น foundation/preview ตามที่ระบุใน SPA/README.md:13

  ส่วนที่ยังไม่ได้เชื่อมจริง ได้แก่:

  - Booking write API และ Firestore transaction
  - Firebase Authentication
  - LIFF / LINE Login
  - LINE webhook handler
  - LINE Messaging API sender
  - Cloud Tasks / Cloud Scheduler
  - reCAPTCHA verification
  - Playwright E2E configuration
  - Firestore/Auth Emulator configuration
  - Admin actions และ Customer submit button ยังถูก disabled

  ดังนั้นคู่มือนี้แบ่งเป็น 3 ระดับ:

   ระดับ       สิ่งที่ทดสอบ                                          สถานะ
  ━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Level 1    Unit tests, API smoke tests, UI preview           รันได้แล้ว
  ─────────  ────────────────────────────────────────────────  ─────────────────────────────────────────
   Level 2    Local E2E ผ่าน Emulator และ LINE provider stubs    ต้อง implement เพิ่ม
  ─────────  ────────────────────────────────────────────────  ─────────────────────────────────────────
   Level 3    Pre-production E2E กับ LINE test channels จริง      ต้อง implement และ deploy spa-*-test ก่อน

  ———

  ## 1. Tests ที่คุณสามารถรันได้ตอนนี้

  ### 1.1 ติดตั้ง Frontend dependencies

  ต้องใช้ Node.js 24 ตาม .nvmrc

  cd /Users/chonlathansongsri/Documents/Manee-son/The49/The49-receipt/SPA

  nvm use
  npm ci

  จากนั้นรัน:

  npm test
  npm run lint
  npm run typecheck
  npm run build

  ผลที่ผมตรวจสอบล่าสุด:

  - Shared TypeScript tests: 2 passed
  - ESLint: passed
  - TypeScript typecheck: passed

  ### 1.2 รัน API tests

  ต้องมี Python 3.12 และ uv

  cd SPA/services/api

  uv sync --extra dev --frozen
  uv run pytest

  ผลปัจจุบัน:

  17 passed

  รัน API สำหรับ manual smoke test:

  uv run uvicorn app.main:app --reload --port 8080

  ตรวจสอบ:

  curl -fsS http://127.0.0.1:8080/health/live
  curl -fsS http://127.0.0.1:8080/health/ready
  curl -fsS http://127.0.0.1:8080/api/v1/public/services

  Availability API ปัจจุบันจะคืน slots: [] และ RESOURCE_CONFIGURATION_REQUIRED โดยตั้งใจ เพราะยังไม่มี resource/capacity configuration

  ### 1.3 รัน Notification Worker tests

  cd SPA/services/notification-worker

  uv sync --extra dev --frozen
  uv run pytest

  ผลปัจจุบัน:

  3 passed

  รัน Worker:

  uv run uvicorn app.main:app --reload --port 8081

  ตรวจสอบ:

  curl -fsS http://127.0.0.1:8081/health/live
  curl -fsS http://127.0.0.1:8081/health/ready

  ### 1.4 เปิด UI preview

  เปิดคนละ Terminal:

  cd SPA
  npm run dev:customer

  Customer Web:

  http://localhost:3000

  อีก Terminal:

  cd SPA
  npm run dev:admin

  Admin Web:

  http://localhost:3001

  ตอนนี้ UI ใช้ preview data เท่านั้น จึงใช้ตรวจ layout, responsive behavior และ navigation ได้ แต่ยังทดสอบการสร้างหรือยืนยัน Booking จริงไม่ได้

  ———

  ## 2. Environment ที่ควรใช้สำหรับ Full E2E

  ควรแยก environment ดังนี้:

   Environment    Firestore/Auth                        LINE                                 วัตถุประสงค์
  ━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━
   Local/CI       Firebase Emulator + synthetic data    Provider stubs                       Automated E2E
  ─────────────  ────────────────────────────────────  ───────────────────────────────────  ────────────────────────
   Test Cloud     แยก test database/resources           LINE test channels และ test group    Manual integration/E2E
  ─────────────  ────────────────────────────────────  ───────────────────────────────────  ────────────────────────
   Production     Named database spa                    Production LINE channels             UAT/production เท่านั้น

  CI ต้องไม่ใช้ production LINE credentials, production Group ID หรือ production Firestore data ตาม SPA/Document/TDD.md:852

  ———

  ## 3. Local E2E Environment ที่ควรเพิ่ม

  ### 3.1 เครื่องมือที่ต้องติดตั้ง

  - Node.js 24
  - Python 3.12
  - uv
  - Java JDK 11 หรือใหม่กว่า
  - Firebase CLI
  - Playwright browsers

  Firebase Emulator ต้องใช้ Java และสามารถรัน Firestore/Auth แยกจาก production ได้อย่างปลอดภัย Firebase Emulator documentation
  (https://firebase.google.com/docs/emulator-suite/install_and_configure)

  หลังเพิ่ม Playwright dependency แล้วจะติดตั้ง browser ด้วย:

  npx playwright install

  ### 3.2 Firebase Emulator configuration

  Repository ยังไม่มี firebase.json และ firestore.rules จึงต้องสร้างก่อน Full E2E

  แนะนำ ports:

  {
    "emulators": {
      "firestore": {
        "port": 8085
      },
      "auth": {
        "port": 9099
      },
      "ui": {
        "enabled": true,
        "port": 4000
      }
    }
  }

  ใช้ Firestore port 8085 เพื่อไม่ชนกับ API port 8080

  รัน Emulator:

  firebase emulators:start \
    --only firestore,auth \
    --project demo-spa49

  เปิด Emulator UI:

  http://localhost:4000

  สำหรับ CI ควรใช้:

  firebase emulators:exec \
    --only firestore,auth \
    --project demo-spa49 \
    "npm run test:e2e"

  ### 3.3 API local E2E environment

  ตัวอย่างค่าที่ API จะต้องรองรับหลัง integration ถูก implement:

  APP_ENV=test
  GCP_PROJECT_ID=demo-spa49
  GOOGLE_CLOUD_PROJECT=demo-spa49
  GCP_REGION=asia-southeast1

  FIRESTORE_DATABASE=(default)
  FIRESTORE_EMULATOR_HOST=127.0.0.1:8085
  FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099

  DEFAULT_BRANCH_ID=branch_001
  BOOKING_BASE_URL=http://localhost:3000
  ADMIN_BASE_URL=http://localhost:3001
  API_BASE_URL=http://localhost:8080
  CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001

  TASK_QUEUE_NAME=spa-line-notifications-test
  TASK_QUEUE_REGION=asia-southeast1

  CAPACITY_BUCKET_MINUTES=15
  IDEMPOTENCY_TTL_HOURS=24
  ACTIVE_PENDING_PER_PHONE=2

  HEALTH_RETENTION_POLICY_APPROVED=false

  ใน Local/CI ต้องมี test-only adapters เช่น:

  - LineIdentityVerifierStub
  - LineMessagingClientStub
  - RecaptchaVerifierStub
  - In-memory หรือ fake Cloud Tasks dispatcher

  Stubs ต้องเปิดได้เฉพาะ APP_ENV=test และ production startup ต้องปฏิเสธ stub configuration

  ### 3.4 Frontend environment

  ชื่อต่อไปนี้เป็น configuration contract ที่ควร implement โดยอิง SPA/Document/LLD.md:1389:

  NEXT_PUBLIC_APP_ENV=test
  NEXT_PUBLIC_API_BASE_URL=http://localhost:8080

  NEXT_PUBLIC_FIREBASE_API_KEY=emulator-placeholder
  NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=localhost
  NEXT_PUBLIC_FIREBASE_PROJECT_ID=demo-spa49
  NEXT_PUBLIC_FIREBASE_APP_ID=emulator-placeholder

  NEXT_PUBLIC_LINE_LIFF_ID=test-stub
  NEXT_PUBLIC_RECAPTCHA_SITE_KEY=test-stub

  คำเตือน: Environment variables เหล่านี้ยังไม่ได้ถูกอ่านโดย frontend ปัจจุบัน จึงต้อง implement integration ก่อน

  ———

  ## 4. การตั้งค่า LINE สำหรับ Pre-production E2E

  แนะนำให้มี LINE resources แยกดังนี้:

  1. Customer LINE Login channel
  2. Customer LIFF app
  3. Customer LINE Official Account + Messaging API channel
  4. Admin LINE Official Account + Messaging API channel
  5. Admin test group
  6. Test LINE user อย่างน้อย 2 บัญชี

  Customer LINE Login channel และ Customer Messaging API channel ต้องอยู่ใต้ LINE Provider เดียวกัน เพื่อให้สามารถ link LINE Official Account และรักษา
  identity boundary ให้ถูกต้อง LINE provider/channel guidance (https://developers.line.biz/en/docs/line-login/link-a-bot/)

  ### 4.1 สร้าง Customer LINE Login channel

  ใน LINE Developers Console:

  1. สร้างหรือเลือก test Provider
  2. สร้าง LINE Login channel
  3. เลือก App type เป็น Web app
  4. ตั้ง Region เป็น Thailand
  5. เก็บค่า:
      - Provider ID
      - Channel ID
      - Channel Secret

  6. อย่าใช้ production channel สำหรับ automated tests

  ### 4.2 สร้าง Customer LIFF app

  ภายใน Customer LINE Login channel:

  1. เพิ่ม LIFF app
  2. ตั้ง Endpoint URL เป็น Customer Web test URL เช่น:

  https://spa-customer-web-test-xxxxx.asia-southeast1.run.app

  3. เลือก Size เป็น Full
  4. เปิด scopes:
      - openid
      - profile

  5. email ไม่จำเป็นสำหรับ Booking flow นี้
  6. เก็บ LIFF ID
  7. ใช้ URL รูปแบบ:

  https://liff.line.me/{LIFF_ID}

  ต้องเปิด openid scope จึงจะเรียก liff.getIDToken() ได้ และควรส่ง raw ID token ไปให้ backend ตรวจสอบ ไม่ควรส่ง userId ที่ frontend อ่านเอง LIFF user identity
  guidance (https://developers.line.biz/en/docs/liff/developing-liff-apps), LINE ID token verification
  (https://developers.line.biz/en/reference/line-login/)

  ### 4.3 สร้าง Customer Messaging API channel

  ปัจจุบัน Messaging API channel ต้องสร้างโดย:

  1. สร้าง LINE Official Account
  2. เปิด Messaging API ผ่าน LINE Official Account Manager
  3. เลือก test Provider ที่ถูกต้อง

  ไม่สามารถสร้าง Messaging API channel ตรงจาก LINE Developers Console แล้ว LINE Messaging API setup
  (https://developers.line.biz/en/docs/messaging-api/getting-started/)

  ตั้งค่า:

  Webhook URL:
  https://{SPA_API_TEST_URL}/api/v1/webhooks/line/customer

  จากนั้น:

  - เปิด Use webhook
  - กด Verify
  - ปิด Auto-reply และ Greeting message หากรบกวน test
  - Issue Channel Access Token
  - เพิ่ม Customer Official Account เป็น friend ใน test LINE account

  Webhook endpoint ต้องคืน 200 สำหรับ verification payload ที่มี events: [] Webhook verification
  (https://developers.line.biz/en/docs/messaging-api/verify-webhook-url/)

  ### 4.4 สร้าง Admin Messaging API channel

  สร้าง LINE Official Account อีกบัญชีสำหรับ Admin notifications แล้วตั้ง:

  Webhook URL:
  https://{SPA_API_TEST_URL}/api/v1/webhooks/line/admin

  จากนั้น:

  1. เปิด Use webhook
  2. เปิด Allow bot to join group chats
  3. เชิญ Admin Official Account เข้า test group
  4. ส่งข้อความจากสมาชิกใน group เพื่อให้ระบบได้รับ signed webhook
  5. นำ source.groupId ไปลงทะเบียนเป็น Admin Group ID

  LINE อนุญาต LINE Official Account ใน group ได้ครั้งละหนึ่งบัญชี และ groupId จะอยู่ใน webhook event LINE group chat documentation
  (https://developers.line.biz/en/docs/messaging-api/group-chats/)

  ไม่ควรพิมพ์ raw Group ID หรือ webhook body ลง application logs ให้บันทึก Group ID ผ่าน Admin-only registration flow หรือ secure bootstrap process

  ### 4.5 Webhook security

  ทั้งสอง endpoints ต้อง:

  - อ่าน raw request body ก่อน parse JSON
  - ตรวจ x-line-signature
  - ใช้ Channel Secret ของ channel นั้นเท่านั้น
  - Reject เมื่อ signature ผิด
  - Reject Customer secret ที่ส่งเข้า Admin endpoint และกลับกัน
  - Deduplicate ด้วย webhookEventId

  LINE แนะนำให้ตรวจ signature แทนการ allowlist IP เพราะ LINE ไม่เปิดเผย webhook source IP LINE signature verification
  (https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/)

  ———

  ## 5. LINE Secret Manager configuration

  TDD ระบุ 11 containers ใน SPA/Document/TDD.md:543

   Secret                                              ค่าที่ต้องใส่
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   spa-line-provider-id                                Customer LINE Provider ID
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-customer-login-channel-id                  LINE Login Channel ID
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-customer-login-channel-secret              LINE Login Channel Secret
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-customer-liff-id                           LIFF ID
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-customer-messaging-channel-id              Customer Messaging Channel ID
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-customer-messaging-channel-secret          Customer Messaging Channel Secret
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-customer-messaging-channel-access-token    Customer Channel Access Token
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-admin-messaging-channel-id                 Admin Messaging Channel ID
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-admin-messaging-channel-secret             Admin Messaging Channel Secret
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-admin-messaging-channel-access-token       Admin Channel Access Token
  ──────────────────────────────────────────────────  ─────────────────────────────────────
   spa-line-admin-group-id                             Registered test/production Group ID

  ข้อควรระวัง:

  - Containers ชุดนี้ดูเป็น production names
  - Test credentials ต้องอยู่ใน test-specific containers เช่น spa-test-line-*
  - ห้ามใส่ test credentials ลง production secret containers โดยไม่ยืนยัน naming policy ก่อน
  - ห้ามใส่ access token หรือ channel secret ลง frontend .env
  - Frontend เปิดเผยได้เฉพาะ LIFF ID และ Channel ID ที่จำเป็น

  Secret Manager รองรับการเพิ่มค่าเป็น version และควร grant Secret Accessor เฉพาะ runtime service account ที่ต้องใช้ Secret Manager version guidance
  (https://cloud.google.com/secret-manager/docs/add-secret-version)

  ———

  ## 6. Firebase Admin environment

  สำหรับ Admin Web pre-production:

  1. เปิด Google Sign-In provider ใน Firebase Authentication
  2. เพิ่ม Admin Web test run.app hostname ใน Authorized domains
  3. สร้าง test invitation document
  4. เมื่อ login ครั้งแรก ให้ bind email กับ Firebase UID
  5. สร้าง app_users/{uid} โดยกำหนด:

  {
    "email": "tester@example.com",
    "role": "ADMIN",
    "active": true,
    "branchIds": ["branch_001"]
  }

  ควรมีอีกบัญชีเป็น STAFF สำหรับตรวจ role matrix

  Firebase ต้องเปิด Google provider และ authorize deployed domain ก่อน Google Sign-In จะทำงาน Firebase Google Sign-In setup
  (https://firebase.google.com/docs/auth/web/google-signin)

  ———

  ## 7. reCAPTCHA Test configuration

  สร้าง reCAPTCHA Enterprise key แยกจาก production:

  - Key สำหรับ positive flow ให้ testing score 1.0
  - Key สำหรับ rejection flow ให้ testing score 0.0
  - Action ต้องเป็น booking_submit
  - Backend ตรวจ:
      - token validity
      - hostname
      - site key
      - action
      - score threshold 0.5

  Google แนะนำให้แยก staging และ production keys และรองรับ test keys ที่คืน score แบบกำหนดไว้ reCAPTCHA test key documentation
  (https://cloud.google.com/recaptcha/docs/create-key-website)

  ———

  ## 8. Cloud Tasks และ private Worker

  Notification Worker ต้องเป็น private Cloud Run service

  ตั้ง queue:

  Queue: spa-line-notifications-test
  Region: asia-southeast1

  Task target:

  https://{WORKER_TEST_URL}/internal/v1/tasks/notifications/{eventId}

  Task ต้องใส่ OIDC token โดยใช้ spa-tasks-invoker-test-sa และตั้ง audience เป็น Worker base URL ส่วน service account ต้องมี roles/run.invoker เฉพาะ Worker
  Cloud Tasks authenticated targets (https://cloud.google.com/tasks/docs/create-tasks)

  Cloud Scheduler reconciliation:

  POST /internal/v1/outbox:reconcile
  Schedule: every 5 minutes
  Authentication: OIDC

  ———

  ## 9. Deployment order สำหรับ Test Environment

  ห้ามรัน deployment scripts ด้วยการตั้งเพียง CHECK_MAIN_BRANCH=false เพราะ default SERVICE_NAME เป็น production names

  ต้อง override อย่างน้อย:

  - SERVICE_NAME=spa-*-test
  - RUNTIME_SERVICE_ACCOUNT=<test-service-account>
  - ENV_FILE=<test-env-file>
  - MIN_INSTANCES=0

  ลำดับที่แนะนำ:

  1. Provision test Firestore, service accounts, IAM, Secret Manager และ Cloud Tasks
  2. Deploy spa-notification-worker-test
  3. นำ Worker URL ไปตั้ง WORKER_TASK_URL และ WORKER_TASK_AUDIENCE
  4. Deploy spa-api-test
  5. นำ API URL ไปใส่ frontend environments
  6. Deploy spa-customer-web-test
  7. Deploy spa-admin-web-test
  8. Update API:
      - BOOKING_BASE_URL
      - ADMIN_BASE_URL
      - API_BASE_URL
      - CORS_ALLOWED_ORIGINS

  9. Redeploy API
  10. ตั้ง LINE LIFF Endpoint URL, webhook URLs และ Firebase Authorized domains ด้วย URLs สุดท้าย

  ———

  ## 10. Full E2E scenarios ที่ควรรัน

  รายละเอียดตรงกับรายการเป้าหมายใน SPA/Document/LLD.md:1592

  ### Guest Booking

  1. เปิด Customer Web
  2. เลือก service, participant และ slot
  3. กรอก nickname/phone/consent
  4. ผ่าน reCAPTCHA
  5. Submit
  6. ตรวจ Booking เป็น PENDING
  7. ตรวจ capacity reservation
  8. ตรวจ secure status link
  9. ตรวจว่า fragment token ถูกลบออกจาก address bar
  10. ตรวจว่า public response ไม่มี health detail

  ### LINE-linked Booking

  1. เปิดผ่าน LIFF URL
  2. Login ด้วย test LINE account
  3. Frontend ส่ง raw LINE ID token ไป API
  4. API verify token กับ Customer Login Channel ID
  5. สร้าง Booking พร้อม verified LINE link
  6. Worker ส่ง pending message ให้ Customer
  7. Worker ส่ง new-booking message เข้า Admin Group
  8. ตรวจว่า Customer message ไม่มี health information
  9. Admin Group เห็นได้เพียง health boolean indicator

  ### Admin Group confirmation

  1. กด/ส่ง confirm command จาก registered Admin Group
  2. API ตรวจ signature, Group ID และ User ID
  3. Booking เปลี่ยน PENDING → CONFIRMED
  4. มี audit event
  5. Customer ได้ confirmed message
  6. ส่ง command เดิมซ้ำแล้วต้องไม่ confirm ซ้ำ

  ### Firebase Admin flow

  1. Login ด้วย invited ADMIN
  2. Confirm/cancel Booking
  3. Assign therapist
  4. Start Booking เฉพาะเมื่อ assigned ครบ
  5. Complete/no-show
  6. Login ด้วย STAFF
  7. ตรวจว่า STAFF เข้า users, roles, security, LINE groups และ global audit ไม่ได้
  8. เรียก API ตรงแล้วยังต้องได้ 403 ไม่ใช่แค่ซ่อนเมนู

  ### Negative/security cases

  - LINE signature ผิด
  - Customer/Admin channel secret สลับกัน
  - Group ไม่ได้ลงทะเบียน
  - Webhook ไม่มี User ID
  - reCAPTCHA score ต่ำกว่า 0.5
  - Slot ถูกจองก่อนกด Submit
  - Submit ซ้ำด้วย Idempotency-Key เดิม
  - Cloud Task ถูก redeliver
  - LINE API คืน retryable 5xx
  - LINE API คืน permanent 4xx
  - Health detail ปรากฏใน response, task, message หรือ logs ต้องทำให้ test fail

  ———

  ## สรุป

  คุณสามารถรัน unit tests, API smoke tests และ UI preview ได้แล้ว แต่ Full E2E ยังต้อง implement infrastructure/test harness และ integrations
  ที่กล่าวข้างต้นก่อน โดยลำดับพัฒนาที่เหมาะสมคือ:

  1. Firebase Emulator + Firestore repositories
  2. Booking/availability write APIs
  3. Firebase Auth
  4. Test provider adapters
  5. LINE Login/webhooks/worker
  6. Cloud Tasks
  7. reCAPTCHA
  8. Playwright E2E suite
  9. Test Cloud deployment
  10. Live LINE test-channel verification

  Production LINE channels หรือ production secrets ไม่ควรถูกนำมาใช้จนกว่า automated tests และ spa-*-test integration จะผ่านทั้งหมดก่อน