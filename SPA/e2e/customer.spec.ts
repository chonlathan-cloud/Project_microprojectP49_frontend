import { expect, test } from "@playwright/test";

const customerUrl =
  process.env.SPA_CUSTOMER_URL ??
  "https://spa-customer-web-test-439060579730.asia-southeast1.run.app";

test("customer catalog, legal pages, and responsive layout are available", async ({ page }) => {
  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await expect(page.getByText(/เชื่อมต่อ SPA API และข้อมูลบริการจริงแล้ว/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Complete Relaxation Ritual" })).toBeVisible();
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);

  await page.goto(`${customerUrl}/privacy`, { waitUntil: "networkidle" });
  await expect(page.getByText(/ฉบับร่าง/).first()).toBeVisible();

  await page.goto(`${customerUrl}/terms`, { waitUntil: "networkidle" });
  await expect(page.getByText(/24 ชั่วโมง/).first()).toBeVisible();
});

test("booking flow can reach live availability without creating a booking", async ({ page }) => {
  await page.goto(customerUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /105 min/ }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await page.getByRole("button", { name: "ดำเนินการต่อ" }).click();
  await expect(page.getByRole("heading", { name: /เลือกวันและเวลา/ })).toBeVisible();
  const schedule = page.getByRole("region", { name: "เลือกวันและเวลา" });
  await schedule.getByRole("button").first().click();
  await expect(schedule.getByRole("status")).toContainText(/Availability API|ไม่พบเวลาว่าง|เวลานี้มาจาก/);
});
