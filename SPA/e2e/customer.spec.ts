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
