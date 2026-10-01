import { expect, test } from "@playwright/test";

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
