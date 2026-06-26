import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for ZORY family-living-room placement testing.
 * Assumes the Next dev server is already running on :3000 and the FastAPI
 * backend on :8000 (the placement/plan pipeline is LLM-backed, so runs are
 * slow and non-deterministic — timeouts are generous and retries are off so
 * flakiness surfaces rather than hides).
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // the LLM pipeline + single shared backend → run serially
  workers: 1,
  retries: 0,
  timeout: 180_000, // a full 9-step placement run hits the LLM ~10x
  expect: { timeout: 30_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
