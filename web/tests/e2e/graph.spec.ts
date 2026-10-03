import { expect, test } from "@playwright/test";

test("extract, review and browse the graph", async ({ page }) => {
  // Extraction runs in the worker and can take a while; the default 30s is too short.
  test.setTimeout(150_000);
  await page.goto("/review");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Run extraction" }).click();
  await page.getByRole("menuitem", { name: "New notes" }).click();

  // Extraction runs in the worker; the cards appear once it has finished.
  const nas = page.getByRole("article", { name: "NAS" });
  const proxmox = page.getByRole("article", { name: "Proxmox" });
  // The worker extracts in the background; the Review queue refreshes by itself.
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
