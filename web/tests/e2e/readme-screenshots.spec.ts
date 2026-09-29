import { expect, test } from "@playwright/test";

test.skip(!process.env.README_SHOTS, "Set README_SHOTS=1 to refresh README screenshots");

test("ask screen", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/ask");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Ask privately").fill("What do my notes say about backups?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();
  await page.screenshot({ path: "../docs/images/readme/ask.jpg", type: "jpeg", quality: 85 });
});
