import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";
import { defineConfig, devices } from "@playwright/test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const testEnv = parseEnv(readFileSync(join(root, ".env.test"), "utf8"));
const apiPort = testEnv.SB_API_PORT ?? "8001";
const webPort = testEnv.SB_WEB_PORT ?? "5174";
const baseURL = `http://localhost:${webPort}`;
const fakeOllamaPort = "11501";
const fakeOllamaURL = `http://127.0.0.1:${fakeOllamaPort}`;

const inheritedEnv = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);

// Explicit test values override anything just loaded from the developer's .env.
const serverEnv = {
  ...inheritedEnv,
  DATABASE_URL: testEnv.TEST_DATABASE_URL ?? "",
  SB_OWNER_PASSWORD_HASH: testEnv.SB_OWNER_PASSWORD_HASH ?? "",
  SB_ALLOWED_ORIGINS: baseURL,
  SB_API_PORT: apiPort,
  SB_WEB_PORT: webPort,
  SB_ENV: "dev",
  SB_COOKIE_SECURE: "false",
  SB_OLLAMA_ENDPOINTS: JSON.stringify([{ label: "e2e", url: fakeOllamaURL, model: "fake-model" }]),
  SB_CHAT_STATUS_TTL_SECONDS: "0",
  SB_ANTHROPIC_API_KEY: "",
  FAKE_OLLAMA_PORT: fakeOllamaPort,
};

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "pnpm exec tsx tests/e2e/fixtures/fake-ollama.ts",
      url: `${fakeOllamaURL}/api/version`,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 30_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    },
    {
      command: `uv run --directory ../backend ai-second-brain serve --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/api/health`,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 60_000,
      // Linux CI hung on the default SIGKILL teardown; ask nicely, then force.
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    },
    {
      command: "pnpm exec vite",
      url: baseURL,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 60_000,
      // Linux CI hung on the default SIGKILL teardown; ask nicely, then force.
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    },
  ],
});
