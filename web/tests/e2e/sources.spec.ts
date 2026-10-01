import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-test-password";

test("the worker indexes the fixture vault and Sources shows it", async ({ page }) => {
  await page.goto("/sources");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/sources$/);
  const table = page.getByRole("table");
  await expect(table.getByText("Projects/NAS.md")).toBeVisible({ timeout: 30_000 });
  // Other specs may add notes (a capture lands in Inbox/), so check each fixture note, not a count.
  for (const path of [
    "Projects/NAS.md",
    "Projects/Proxmox.md",
    "Ideas/Second brain.md",
    "Journal/2026-09-30.md",
    "Reading/Designing Data-Intensive Applications.md",
  ]) {
    const row = table.getByRole("row").filter({ hasText: path });
    await expect(row).toBeVisible({ timeout: 60_000 });
    await expect(row.getByText("Searchable")).toBeVisible({ timeout: 60_000 });
  }
  await expect(table.getByText(".obsidian/workspace.md")).toHaveCount(0);
  const embedded = page.getByText("Embedded", { exact: true }).locator("xpath=..");
  await expect(embedded.getByText("100%", { exact: true })).toBeVisible({ timeout: 60_000 });

  // A scan of 5 notes can finish before the UI shows "Scan queued…", so assert the
  // round trip by its outcome: the POST is accepted and the screen's own polling
  // then sees a finished manual run.
  const scan = page.getByRole("button", { name: "Scan now" });
  const queued = page.waitForResponse(
    (r) => r.url().endsWith("/api/sources/reconcile") && r.request().method() === "POST",
  );
  const finished = page.waitForResponse(
    async (r) => {
      if (!r.url().endsWith("/api/sources/summary") || !r.ok()) return false;
      const run = (await r.json()).last_run;
      return run?.trigger === "manual" && run.finished_at !== null;
    },
    { timeout: 30_000 },
  );
  await scan.click();
  expect((await queued).status()).toBe(202);
  const run = (await (await finished).json()).last_run;
  expect(run.outcome).toBe("ok");
  await expect(scan).toBeEnabled();
  const lastScan = page.getByText("Last scan", { exact: true }).locator("..");
  await expect(lastScan.getByText("just now")).toBeVisible();
});
