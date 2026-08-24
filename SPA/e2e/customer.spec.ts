import { expect, test } from "@playwright/test";

const customerUrl =
  process.env.SPA_CUSTOMER_URL ??
  "https://spa-customer-web-test-439060579730.asia-southeast1.run.app";

async function chooseFirstBookableDate(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: /วันที่เข้ารับบริการ|Appointment date/ }).click();
  const calendar = page.getByRole("dialog", { name: /เลือกวันที่|Choose a date/ });
  await calendar.locator(".calendar-grid button:not(:disabled)").first().click();
  await calendar.getByRole("button", { name: /ใช้วันที่นี้|Use this date/ }).click();
}

test("customer catalog keeps bilingual descriptions while the API is being upgraded", async ({ page }) => {
  await page.route("**/api/spa/api/v1/public/services", async (route) => {
    await route.fulfill({
      json: {
        catalogVersion: "firestore",
        items: [{
          id: "complete-relaxation",
          category: "SIGNATURE",
          nameTh: "แพ็กเกจผ่อนคลายครบสูตร",
          nameEn: "Complete Relaxation Ritual",
          descriptionTh: null,
          descriptionEn: null,
          active: true,
          displayOrder: 10,
          variants: [{
            id: "complete-relaxation-105",
            durationMinutes: 105,
            priceSatang: 59000,
            pricingMode: "PER_PARTICIPANT",
            requiredPax: 1
          }]
        }]
      }
    });
  });

  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await expect(page.getByText("โปรแกรมผ่อนคลายแบบครบขั้นตอนในคอร์สเดียว")).toBeVisible();
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await expect(page.getByText(/A complete relaxation ritual in one session/)).toBeVisible();
});

test("customer catalog, legal pages, and responsive layout are available", async ({ page }) => {
  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "เลือกเวลาพักของคุณ" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Complete Relaxation Ritual" })).toBeVisible();
  await expect(page.getByText("โปรแกรมผ่อนคลายแบบครบขั้นตอนในคอร์สเดียว")).toBeVisible();
  await expect(page.locator(".service-media img").first()).toBeVisible();
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);
  const columns = await page.locator(".service-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
  expect(columns).toBe((page.viewportSize()?.width ?? 0) >= 1024 ? 3 : (page.viewportSize()?.width ?? 0) >= 641 ? 2 : 1);

  await page.goto(`${customerUrl}/privacy`, { waitUntil: "networkidle" });
  await expect(page.getByText(/ฉบับร่าง/).first()).toBeVisible();

  await page.goto(`${customerUrl}/terms`, { waitUntil: "networkidle" });
  await expect(page.getByText(/24 ชั่วโมง/).first()).toBeVisible();
});

test("English duration and price labels do not overlap", async ({ page }) => {
  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await page.getByRole("tab", { name: "Massage & spa" }).click();

  const options = page.locator(".variant");
  await expect(options.first()).toContainText("฿");
  await expect(options.first()).not.toContainText("THB");
  const hasOverlap = await options.evaluateAll((elements) => elements.some((element) => {
    const duration = element.querySelector(".variant-duration")?.getBoundingClientRect();
    const price = element.querySelector(".variant-price")?.getBoundingClientRect();
    const indicator = element.querySelector(".variant-indicator")?.getBoundingClientRect();
    return !duration || !price || !indicator || duration.right > price.left || price.right > indicator.left;
  }));
  expect(hasOverlap).toBe(false);
});

test("booking flow can reach live availability without creating a booking", async ({ page }) => {
  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /105 (min|นาที)/ }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await expect(page.getByText("ขั้นตอน 2 จาก 5")).toBeVisible();
  await expect(page.getByText("แพ็กเกจผ่อนคลายครบสูตร")).toBeVisible();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await expect(page.getByRole("heading", { name: /เลือกวันและเวลา/ })).toBeVisible();
  const schedule = page.getByRole("region", { name: "เลือกวันและเวลา" });
  await expect(schedule.getByRole("status")).toContainText(/เลือกวันที่เพื่อดูเวลาว่าง/);
  await chooseFirstBookableDate(page);
  await expect(schedule.getByRole("status")).toContainText(/พบ \d+ ช่วงเวลา|วันนี้ไม่มีเวลาว่าง|ตรวจสอบเวลาว่างไม่สำเร็จ/);
});

test("a booking conflict returns the guest to refreshed time selection", async ({ page }) => {
  await page.route("**/api/spa/api/v1/public/availability/search", async (route) => {
    await route.fulfill({ json: { slots: [{ localDate: "2026-08-18", localStartTime: "10:00", availableUnits: 1 }, { localDate: "2026-08-18", localStartTime: "10:15", availableUnits: 1 }] } });
  });
  let bookingAttempts = 0;
  await page.route("**/api/spa/api/v1/public/bookings", async (route) => {
    bookingAttempts += 1;
    if (bookingAttempts === 1) {
      await route.fulfill({ status: 409, contentType: "application/problem+json", json: { code: "CAPACITY_UNAVAILABLE", detail: "Selected slot is no longer available" } });
      return;
    }
    await route.fulfill({ json: { bookingId: "BK-TEST-001", statusToken: "test-status-token" } });
  });

  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /105 (min|นาที)/ }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await expect(page.getByText("จองล่วงหน้าได้ 1–30 วัน")).toBeVisible();
  await chooseFirstBookableDate(page);
  let schedule = page.getByRole("region", { name: "เลือกวันและเวลา" });
  await schedule.getByRole("button", { name: "10:00" }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await page.getByRole("textbox", { name: "เบอร์โทรศัพท์ผู้ติดต่อหลัก" }).fill("0812345678");
  await page.getByRole("textbox", { name: "ชื่อเล่น" }).fill("ทดสอบ");
  await page.getByRole("radio", { name: "ไม่มีข้อมูลสุขภาพที่ต้องแจ้ง" }).check();
  await page.getByRole("checkbox").first().check();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "ส่งคำขอจอง" }).click();

  const conflict = page.getByRole("dialog", { name: "ช่วงเวลานี้เพิ่งถูกจอง" });
  await expect(conflict).toBeVisible();
  await conflict.getByRole("button", { name: "เลือกเวลาใหม่" }).click();
  schedule = page.getByRole("region", { name: "เลือกวันและเวลา" });
  await schedule.getByRole("button", { name: "10:15" }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await expect(page.getByRole("textbox", { name: "เบอร์โทรศัพท์ผู้ติดต่อหลัก" })).toHaveValue("0812345678");
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await page.getByRole("button", { name: "ส่งคำขอจอง" }).click();

  await expect(page.getByRole("heading", { name: "ส่งคำขอเรียบร้อยแล้ว" })).toBeVisible();
  await expect(page.getByText("รอร้านยืนยัน")).toBeVisible();
  await expect(page.getByText("BK-TEST-001")).toBeVisible();
  await expect(page.getByRole("link", { name: "ตรวจสอบสถานะการจอง" })).toBeVisible();
});

test("LINE campaign registration issues one digital coupon", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "liff", {
      value: {
        init: async ({ liffId }: { liffId: string }) => {
          (window as Window & { initializedLiffId?: string }).initializedLiffId = liffId;
        },
        isLoggedIn: () => true,
        isInClient: () => true,
        login: () => undefined,
        getIDToken: () => "test-line-id-token-with-minimum-length",
        getFriendship: async () => ({ friendFlag: true }),
        requestFriendship: async () => undefined,
        closeWindow: () => undefined
      },
      configurable: true
    });
  });
  await page.route("**/api/config", async (route) => {
    await route.fulfill({
      json: {
        lineLiffId: "booking-test-liff-id",
        lineCampaignV1LiffId: "campaign-v1-test-liff-id"
      }
    });
  });
  await page.route("**/api/spa/api/v1/public/campaigns/welcome-50", async (route) => {
    await route.fulfill({
      json: {
        code: "welcome-50",
        nameTh: "รับส่วนลด 50 บาท",
        nameEn: "Get THB 50 off",
        descriptionTh: "ลงทะเบียนครั้งเดียวเพื่อรับคูปองส่วนลดสำหรับใช้ที่ SPA 49",
        descriptionEn: "Register once to receive a SPA 49 discount coupon.",
        benefit: { amountSatang: 5000, currency: "THB" },
        eligibility: { requiresFollowing: true }
      }
    });
  });
  await page.route("**/api/spa/api/v1/public/campaigns/welcome-50/claims", async (route) => {
    const request = route.request();
    expect(request.headers()["idempotency-key"]).toBeTruthy();
    expect(request.postDataJSON()).toMatchObject({
      fullName: "มณี สุขใจ",
      phone: "0812345678",
      birthDay: 29,
      birthMonth: 2,
      privacyAcknowledged: true,
      birthdayMarketingConsent: false,
      lineFriendshipConfirmed: true
    });
    await route.fulfill({
      status: 201,
      json: {
        campaignCode: "welcome-50",
        alreadyClaimed: false,
        coupon: {
          code: "W50-TEST123456",
          status: "ISSUED",
          amountSatang: 5000,
          currency: "THB",
          issuedAt: "2026-08-20T10:00:00Z",
          expiresAt: null
        }
      }
    });
  });

  await page.goto(`${customerUrl}/offers/welcome-50`, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "รับส่วนลด 50 บาท" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as Window & { initializedLiffId?: string }).initializedLiffId)).toBe("campaign-v1-test-liff-id");
  await page.getByRole("textbox", { name: /ชื่อ-นามสกุล/ }).fill("มณี สุขใจ");
  await page.getByRole("textbox", { name: /เบอร์โทรศัพท์/ }).fill("0812345678");
  await page.locator("#campaign-birth-day").selectOption("29");
  await page.locator("#campaign-birth-month").selectOption("2");
  await page.getByRole("checkbox").first().check();
  await page.getByRole("button", { name: "ยืนยันรับสิทธิ์ 50 บาท" }).click();

  await expect(page.getByRole("heading", { name: "รับคูปองเรียบร้อยแล้ว" })).toBeVisible();
  await expect(page.getByText("W50-TEST123456")).toBeVisible();
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);
});

test("LINE campaign asks non-followers to add the OA before showing PII fields", async ({ page }) => {
  await page.addInitScript(() => {
    let friendFlag = false;
    Object.defineProperty(window, "liff", {
      value: {
        init: async () => undefined,
        isLoggedIn: () => true,
        isInClient: () => true,
        login: () => undefined,
        getIDToken: () => "test-line-id-token-with-minimum-length",
        getFriendship: async () => ({ friendFlag }),
        requestFriendship: async () => { friendFlag = true; },
        closeWindow: () => undefined
      },
      configurable: true
    });
  });
  await page.route("**/api/config", async (route) => {
    await route.fulfill({ json: { lineCampaignV1LiffId: "campaign-v1-test-liff-id" } });
  });
  await page.route("**/api/spa/api/v1/public/campaigns/welcome-50", async (route) => {
    await route.fulfill({
      json: {
        code: "welcome-50",
        nameTh: "รับส่วนลด 50 บาท",
        nameEn: "Get THB 50 off",
        benefit: { amountSatang: 5000, currency: "THB" },
        eligibility: { requiresFollowing: true }
      }
    });
  });

  await page.goto(`${customerUrl}/offers/welcome-50`, { waitUntil: "networkidle" });

  await expect(page.getByRole("heading", { name: "เพิ่มเพื่อน SPA 49 ก่อนรับสิทธิ์" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /ชื่อ-นามสกุล/ })).toHaveCount(0);
  await page.getByRole("button", { name: "เพิ่มเพื่อนและตรวจสอบ" }).click();
  await expect(page.getByRole("textbox", { name: /ชื่อ-นามสกุล/ })).toBeVisible();
});

test("LINE customer can review upcoming bookings and history without exposing PII", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "liff", {
      value: {
        init: async () => undefined,
        isLoggedIn: () => true,
        isInClient: () => true,
        login: () => undefined,
        getIDToken: () => "test-line-id-token-with-minimum-length",
        getFriendship: async () => ({ friendFlag: true })
      },
      configurable: true
    });
  });
  await page.route("**/api/config", async (route) => {
    await route.fulfill({ json: { lineLiffId: "booking-test-liff-id" } });
  });
  await page.route("**/api/spa/api/v1/customer/bookings:list", async (route) => {
    const request = route.request().postDataJSON() as { lineIdToken: string; view: string };
    expect(request.lineIdToken).toBe("test-line-id-token-with-minimum-length");
    const items = request.view === "UPCOMING" ? [{
      bookingId: "BK-20260825-ABC123",
      status: "CONFIRMED",
      localDate: "2026-08-25",
      localStartTime: "10:00",
      timezone: "Asia/Bangkok",
      serviceNamesTh: ["นวดอโรม่า"],
      serviceNamesEn: ["Aroma Therapy"],
      pax: 1,
      estimatedAmountSatang: 50000,
      priceIncludesVat: true
    }] : [];
    await route.fulfill({ json: { items, nextPageToken: null } });
  });

  await page.goto(`${customerUrl}/my-bookings`, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "การจองของฉัน" })).toBeVisible();
  await expect(page.getByRole("img", { name: "SPA 49" })).toBeVisible();
  await expect(page.getByText("นัดหมายถัดไป")).toBeVisible();
  await expect(page.getByText("นวดอโรม่า")).toBeVisible();
  await page.getByText("ดูรายละเอียด").click();
  await expect(page.getByText("BK-20260825-ABC123")).toBeVisible();
  expect(await page.getByText("0812345678").count()).toBe(0);

  await page.getByRole("tab", { name: "ประวัติ" }).click();
  await expect(page.getByRole("heading", { name: "ยังไม่มีประวัติการจอง" })).toBeVisible();
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);
});

test("My Bookings resumes after delayed LIFF authentication", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "liff", {
      value: {
        init: async () => new Promise<void>((resolve) => window.setTimeout(resolve, 1_000)),
        isLoggedIn: () => true,
        isInClient: () => true,
        login: () => undefined,
        getIDToken: () => "delayed-line-id-token-with-minimum-length",
        getFriendship: async () => ({ friendFlag: true })
      },
      configurable: true
    });
  });
  await page.route("**/api/config", async (route) => {
    await route.fulfill({ json: { lineLiffId: "booking-test-liff-id" } });
  });
  await page.route("**/api/spa/api/v1/customer/bookings:list", async (route) => {
    expect(route.request().postDataJSON()).toMatchObject({
      lineIdToken: "delayed-line-id-token-with-minimum-length",
      view: "UPCOMING"
    });
    await route.fulfill({ json: { items: [], nextPageToken: null } });
  });

  await page.goto(`${customerUrl}/my-bookings`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("tab", { name: "กำลังจะมาถึง" })).toBeDisabled();
  await expect(page.getByText("กำลังยืนยันบัญชี LINE…")).toBeVisible();
  await expect(page.getByRole("heading", { name: "ยังไม่มีการจองที่กำลังจะมาถึง" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "กำลังจะมาถึง" })).toBeEnabled();
});
