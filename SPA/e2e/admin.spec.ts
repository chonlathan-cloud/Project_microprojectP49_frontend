import { expect, test } from "@playwright/test";

const adminUrl =
  process.env.SPA_ADMIN_URL ??
  "https://spa-admin-web-test-439060579730.asia-southeast1.run.app";

test("admin login shell loads and remains responsive", async ({ page }) => {
  await page.goto(adminUrl, { waitUntil: "networkidle" });
  await expect(page.getByRole("button", { name: /Google/i })).toBeVisible();
  await expect(page.getByText(/SPA 49 Admin/i)).toBeVisible();
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);
});
