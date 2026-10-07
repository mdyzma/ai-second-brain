import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-test-password"; // matches the committed test-only hash in .env.test

async function signIn(page: import("@playwright/test").Page, password: string) {
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("protected pages redirect to login and keep the destination", async ({ page }) => {
  await page.goto("/nodes");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await signIn(page, PASSWORD);
  await expect(page).toHaveURL(/\/nodes$/);
  await expect(page.getByRole("heading", { name: "Nodes" })).toBeVisible();
});

test("wrong password shows an error", async ({ page }) => {
  await page.goto("/login");
  await signIn(page, "definitely-wrong");
  await expect(page.getByRole("alert")).toHaveText("Incorrect password");
  await expect(page).toHaveURL(/\/login/);
});

test("login lands on Digest with navigation; theme toggles; logout returns to login", async ({
  page,
}) => {
  await page.goto("/");
  await signIn(page, PASSWORD);
  await expect(page).toHaveURL(/\/digest$/);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Digest" })).toHaveAttribute("aria-current", "page");

  const html = page.locator("html");
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/ask");
  await expect(page).toHaveURL(/\/login/);
});

test("open-redirect targets are ignored after login", async ({ page }) => {
  await page.goto("/login?redirect=https://evil.example");
  await signIn(page, PASSWORD);
  await expect(page).toHaveURL(/\/digest$/);
});
