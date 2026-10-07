import { expect, test } from "@playwright/test";
import { resetGraph } from "./fixtures/reset-graph";

test.beforeAll(resetGraph);

test("run now fills the digest and review empties it", async ({ page }) => {
  // The digest only closes the run once the extract queue drains, and extraction runs through
  // the worker against the fake Ollama; allow the same budget as graph.spec.ts.
  test.setTimeout(150_000);
  await page.goto("/");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/digest$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/digest$/);
  // Extraction only sees notes the ingest has already recorded, so wait for the fixture vault.
  await expect
    .poll(
      async () => {
        const res = await page.request.get("/api/graph/status");
        return res.ok()
          ? ((await res.json()) as { revisions: { total: number } }).revisions.total
          : 0;
      },
      { timeout: 60_000 },
    )
    .toBeGreaterThanOrEqual(5);

  await page.goto("/digest");
  // Playwright runs with SB_NIGHTLY_ENABLED=false, so the no-runs copy says the schedule is off.
  await expect(page.getByText(/Nightly runs are off/)).toBeVisible();
  // Marks this document so a full page reload would be detected (the digest must fill in live).
  await page.evaluate(() => {
    (window as unknown as { __noReload: boolean }).__noReload = true;
  });
  await page.getByRole("button", { name: "Run now" }).click();
  const review = page.getByRole("region", { name: /To review/ });
  await expect(review.getByRole("link", { name: /^NAS Device / })).toBeVisible({
    timeout: 90_000,
  });
  await expect(review.getByRole("link", { name: /^Proxmox Tool / })).toBeVisible({
    timeout: 90_000,
  });
  expect(
    await page.evaluate(() => (window as unknown as { __noReload?: boolean }).__noReload),
  ).toBe(true);
  // Entities keep arriving while the run's extract jobs drain. The run row itself is closed only
  // by the 15-minute tick, so wait until every queued note has been attempted, then read the count.
  await expect
    .poll(
      async () => {
        const res = await page.request.get("/api/digest");
        if (!res.ok()) return false;
        const { run } = (await res.json()) as {
          run: { done: number; queued_new: number; queued_failed: number };
        };
        return run.done >= run.queued_new + run.queued_failed;
      },
      { timeout: 90_000 },
    )
    .toBe(true);
  await expect(review.getByTestId("remaining")).toHaveText(/^\d+$/);
  const before = Number(await review.getByTestId("remaining").textContent());

  await page.goto("/review");
  await page
    .getByRole("article", { name: "NAS", exact: true })
    .getByRole("button", { name: "Accept" })
    .click();
  await expect(page.getByRole("article", { name: "NAS", exact: true })).toBeHidden();

  await page.goto("/digest");
  await expect(review.getByTestId("remaining")).toHaveText(String(before - 1));
});
