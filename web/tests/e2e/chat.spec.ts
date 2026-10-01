import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "e2e-test-password"; // matches the committed test-only hash in .env.test
const FAKE_OLLAMA = "http://127.0.0.1:11501";
// The test database persists between runs, so titles carry a per-run suffix.
const RUN = Date.now().toString(36);

async function signIn(page: Page): Promise<void> {
  await page.goto("/ask");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/ask$/);
}

test.beforeEach(async ({ request }) => {
  await request.post(`${FAKE_OLLAMA}/__control`, { data: { down: false } });
});

test.afterAll(async ({ request }) => {
  await request.post(`${FAKE_OLLAMA}/__control`, { data: { down: false } });
});

test("a private question shows sources first, then the saved answer", async ({ page }) => {
  await signIn(page);
  await page.getByLabel("Ask privately").fill(`What is in my notes? ${RUN}`);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page).toHaveURL(/\/ask\/[0-9a-f-]{36}$/);

  // The worker has indexed the fixture vault, so the generic question may or may not match
  // notes; either way the sources block must come before the answer.
  const sources = page
    .getByText("No matching local sources — this answer is not based on your notes.")
    .or(page.getByRole("region", { name: "Sources" }))
    .first();
  const answer = page.getByText("This is the fake e2e answer.");
  await expect(sources).toBeVisible();
  await expect(answer).toBeVisible();
  const sourcesFirst = await sources.evaluate((node, answerText) => {
    const target = [...document.querySelectorAll("p")].find((p) => p.textContent === answerText);
    return (
      target !== undefined &&
      Boolean(node.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING)
    );
  }, "This is the fake e2e answer.");
  expect(sourcesFirst).toBe(true);
  await expect(page.getByText("Private · e2e (fake-model)").first()).toBeVisible();

  await page.reload();
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Conversations" })
      .getByText(`What is in my notes? ${RUN}`),
  ).toBeVisible();
});

test("Stop interrupts a slow answer, nothing is saved, and the next question works", async ({
  page,
}) => {
  await signIn(page);
  await page.getByLabel("Ask privately").fill("please be slow");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/word3/)).toBeVisible();
  await page.getByRole("button", { name: "Stop generating" }).click();
  await expect(page.getByText("Stopped — not saved.")).toBeVisible();

  await page.reload();
  // Wait for the reloaded session detail first, so the absence checks are meaningful.
  await expect(page.getByRole("heading", { name: "New conversation" })).toBeVisible();
  await expect(page.getByText(/word3/)).toHaveCount(0);
  await expect(
    page.getByRole("list", { name: "Conversation" }).getByText("please be slow"),
  ).toHaveCount(0);

  await expect(page.getByLabel("Ask privately")).toBeEnabled();
  await page.getByLabel("Ask privately").fill("hello again");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();
});

test("with no reachable local model the banner explains and asking is disabled", async ({
  page,
  request,
}) => {
  await signIn(page);
  await request.post(`${FAKE_OLLAMA}/__control`, { data: { down: true } });
  await page.reload();
  await expect(
    page.getByText(
      "No local model reachable. Private questions can't be answered right now. Nothing was sent to the cloud.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Ask privately")).toBeDisabled();
});

test("cloud mode is offered only when configured", async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole("radio", { name: /Cloud/ })).toBeDisabled();
  await expect(page.getByText("Cloud mode needs SB_ANTHROPIC_API_KEY.")).toBeVisible();
});

test("the first question is sent exactly once", async ({ page }) => {
  await signIn(page);
  await page.getByLabel("Ask privately").fill("count me once");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page).toHaveURL(/\/ask\/[0-9a-f-]{36}$/);
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();

  await page.reload();
  const conversation = page.getByRole("list", { name: "Conversation" });
  await expect(conversation.getByText("This is the fake e2e answer.")).toHaveCount(1);
  await expect(conversation.getByText("count me once")).toHaveCount(1);
});

test("deleting the open conversation returns to Ask", async ({ page }) => {
  await signIn(page);
  await page.getByLabel("Ask privately").fill(`delete me please ${RUN}`);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("This is the fake e2e answer.")).toBeVisible();

  await page.getByRole("button", { name: `Delete conversation: delete me please ${RUN}` }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/ask$/);
  await expect(
    page.getByRole("navigation", { name: "Conversations" }).getByText(`delete me please ${RUN}`),
  ).toHaveCount(0);
});
