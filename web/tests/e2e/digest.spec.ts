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
  await expect(page.getByText(/No nightly run yet/)).toBeVisible();
  await page.getByRole("button", { name: "Run now" }).click();
  const review = page.getByRole("region", { name: /To review/ });
  await expect(review.getByRole("link", { name: /^NAS / })).toBeVisible({
    timeout: 90_000,
  });
  await expect(review.getByRole("link", { name: /^Proxmox / })).toBeVisible({
    timeout: 90_000,
  });
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
