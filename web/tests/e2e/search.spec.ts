import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-test-password";

test.beforeEach(async ({ page }) => {
  await page.goto("/search");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/search/);
});

test("search finds a note by text and filters by tag", async ({ page }) => {
  await page.getByLabel("Search your notes").fill("Dyski");
  const results = page.getByRole("list", { name: "Search results" });
  await expect(results.getByText("Projects/NAS.md")).toBeVisible({ timeout: 60_000 });
  await expect(results.locator("mark", { hasText: /dyski/i }).first()).toBeVisible();
  await page.getByRole("button", { name: "homelab", pressed: false }).click();
  await expect(page).toHaveURL(/tag=.*homelab/);
  await expect(results.getByRole("listitem")).toHaveCount(1);
});

test("a capture becomes searchable", async ({ page }) => {
  await page.getByRole("button", { name: "Capture" }).click();
  await page
    .getByRole("textbox", { name: "Note", exact: true })
    .fill("Test capture e2e\nzebrafish marker");
  await page.keyboard.press("Control+Enter");
  await expect(page.getByText("Saved to Inbox")).toBeVisible();
  const box = page.getByLabel("Search your notes");
  await expect(async () => {
    await box.fill("");
    await box.fill("zebrafish");
    await expect(
      page.getByRole("list", { name: "Search results" }).getByText(/Inbox\/.*Test capture e2e\.md/),
    ).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 45_000 });
});

test("private chat cites the NAS note", async ({ page }) => {
  await page.goto("/ask");
  await page.getByLabel("Ask privately").fill("Kiedy są kopie zapasowe na NAS?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page).toHaveURL(/\/ask\/[0-9a-f-]{36}$/);
  await expect(
    page.getByRole("region", { name: "Sources" }).getByText("Projects/NAS.md"),
  ).toBeVisible({ timeout: 30_000 });
});
