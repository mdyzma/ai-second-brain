import { expect, type Page, test } from "@playwright/test";
import { resetGraph } from "./fixtures/reset-graph";

// Runs through the e2e servers (the `just e2e` harness), so answers come from the fake Ollama.
test.skip(!process.env.README_SHOTS, "Set README_SHOTS=1 to refresh README screenshots");

test("ask screen", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/ask");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Ask privately")).toBeVisible();

  // Start from an empty sidebar: delete leftovers from earlier e2e runs.
  const origin = new URL(baseURL ?? "http://localhost:5174").origin;
  const list = await page.request.get("/api/sessions");
  for (const s of (await list.json()) as { id: string }[]) {
    const res = await page.request.delete(`/api/sessions/${s.id}`, { headers: { Origin: origin } });
    expect(res.ok()).toBeTruthy();
  }
  await page.reload();

  await page.getByLabel("Ask privately").fill("Which ports does the NAS expose?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();

  await page.getByRole("link", { name: "New conversation" }).click();
  await page.getByLabel("Ask privately").fill("What do my notes say about backups?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("This is the fake e2e answer.")).toHaveCount(1);
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();
  await page.screenshot({ path: "../docs/images/readme/ask.jpg", type: "jpeg", quality: 85 });
});

test("sources screen", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/sources");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("table").getByText("Searchable")).toHaveCount(5, { timeout: 60_000 });
  await page.screenshot({ path: "../docs/images/readme/sources.jpg", type: "jpeg", quality: 85 });
});

test("search screen", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/search?q=dyski");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("list", { name: "Search results" }).getByText("Projects/NAS.md"),
  ).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: "../docs/images/readme/search.jpg", type: "jpeg", quality: 85 });
});

test("ask screen with sources", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/ask");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Ask privately").fill("Kiedy są kopie zapasowe na NAS?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page).toHaveURL(/\/ask\/[0-9a-f-]{36}$/);
  await expect(
    page.getByRole("region", { name: "Sources" }).getByText("Projects/NAS.md"),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("This is the fake e2e answer.").first()).toBeVisible();
  await page.screenshot({
    path: "../docs/images/readme/ask-sources.jpg",
    type: "jpeg",
    quality: 85,
  });
});

async function signIn(page: Page, path: string) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(path);
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
}

// Extraction only sees notes the ingest has recorded, so wait for the fixture vault first.
async function extractFixtureVault(page: Page) {
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
  await page.getByRole("button", { name: "Run extraction" }).click();
  await page.getByRole("menuitem", { name: "New notes" }).click();
}

test("review screen", async ({ page }) => {
  test.setTimeout(150_000);
  await signIn(page, "/review");
  await expect(page.getByRole("button", { name: "Run extraction" })).toBeVisible();
  const nas = page.getByRole("article", { name: "NAS", exact: true });
  const proxmox = page.getByRole("article", { name: "Proxmox", exact: true });
  // The cards are already there when an earlier run extracted the vault; otherwise extract now.
  if (!(await nas.isVisible())) await extractFixtureVault(page);
  await expect(nas).toBeVisible({ timeout: 90_000 });
  await expect(proxmox).toBeVisible({ timeout: 90_000 });
  await page.screenshot({ path: "../docs/images/readme/review.jpg", type: "jpeg", quality: 85 });
});

test("entity page", async ({ page }) => {
  test.setTimeout(150_000);
  await signIn(page, "/review");
  await expect(page.getByRole("button", { name: "Run extraction" })).toBeVisible();
  const nas = page.getByRole("article", { name: "NAS", exact: true });
  const proxmox = page.getByRole("article", { name: "Proxmox", exact: true });
  if (!(await nas.isVisible())) {
    await extractFixtureVault(page);
    await nas.waitFor({ timeout: 90_000 }).catch(() => undefined);
    await proxmox.waitFor({ timeout: 30_000 }).catch(() => undefined);
  }
  // Accept both through the UI when they are still waiting; an earlier run may have accepted them.
  for (const card of [nas, proxmox]) {
    if (await card.isVisible().catch(() => false)) {
      await card.getByRole("button", { name: "Accept" }).click();
      await expect(card).toBeHidden();
    }
  }
  // Accept the "Proxmox runs on NAS" link too (as graph.spec.ts does), so the page shows the
  // related entities; an earlier run may have accepted it already.
  await page.getByRole("tab", { name: /Links/ }).click();
  const link = page.getByRole("button", { name: "Accept: Proxmox runs on NAS" });
  await link.waitFor({ timeout: 15_000 }).catch(() => undefined);
  if (await link.isVisible().catch(() => false)) {
    await link.click();
    await expect(link).toBeHidden();
  }
  await page.goto("/entities?type=device");
  await page.getByRole("link", { name: /^NAS/ }).click();
  await expect(page.getByRole("heading", { name: "NAS", level: 1 })).toBeVisible();
  await expect(page.getByText("Projects/NAS.md")).toBeVisible();
  await expect(page.getByText(/Runs:\s*Proxmox/)).toBeVisible();
  await page.screenshot({ path: "../docs/images/readme/entity.jpg", type: "jpeg", quality: 85 });
});

test("digest screen", async ({ page }) => {
  test.setTimeout(150_000);
  // Same guarded reset as digest.spec.ts: it refuses any database that is not the test one.
  resetGraph();
  await signIn(page, "/digest");
  await expect(page.getByRole("button", { name: "Run now" })).toBeVisible();
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
  await page.getByRole("button", { name: "Run now" }).click();
  const review = page.getByRole("region", { name: /To review/ });
  await expect(review.getByRole("link", { name: /^NAS Device / })).toBeVisible({
    timeout: 90_000,
  });
  await expect(review.getByRole("link", { name: /^Proxmox Tool / })).toBeVisible({
    timeout: 90_000,
  });
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
  await page.screenshot({ path: "../docs/images/readme/digest.jpg", type: "jpeg", quality: 85 });
});
