import { expect, test } from "@playwright/test";

test("extract, review and browse the graph", async ({ page }) => {
  // Extraction runs in the worker and can take a while; the default 30s is too short.
  test.setTimeout(150_000);
  await page.goto("/review");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
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
  await page.getByRole("button", { name: "Run extraction" }).click();
  await page.getByRole("menuitem", { name: "New notes" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /Queued [1-9]\d* notes? for extraction/ }),
  ).toBeVisible();

  // The worker extracts in the background; the Review queue refreshes by itself.
  const nas = page.getByRole("article", { name: "NAS", exact: true });
  const proxmox = page.getByRole("article", { name: "Proxmox", exact: true });
  await expect(nas).toBeVisible({ timeout: 90_000 });
  await expect(proxmox).toBeVisible({ timeout: 90_000 });
  await nas.getByRole("button", { name: "Accept" }).click();
  await expect(nas).toBeHidden();
  await proxmox.getByRole("button", { name: "Accept" }).click();
  await expect(proxmox).toBeHidden();

  await page.getByRole("tab", { name: /Links/ }).click();
  await page.getByRole("button", { name: "Accept: Proxmox runs on NAS" }).click();
  await expect(page.getByRole("button", { name: "Accept: Proxmox runs on NAS" })).toBeHidden();

  await page.goto("/entities?type=device");
  await page.getByRole("link", { name: /^NAS/ }).click();
  await expect(page.getByRole("heading", { name: "NAS", level: 1 })).toBeVisible();
  await expect(page.getByText("Projects/NAS.md")).toBeVisible();
  await expect(page.getByText(/Runs:\s*Proxmox/)).toBeVisible();
});
