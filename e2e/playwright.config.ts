import { defineConfig, devices } from "@playwright/test";

/**
 * Browser E2E for the rewrite (review 009). Runs against a RUNNING app on a preview database — never the live pz:
 *   backend:  python -m projectzero.ops.preview create   →   PZ_SCHEMA=<name> python -m projectzero.api
 *   frontend: npm run dev (frontend/)
 *   here:     PZ_BASE_URL=http://localhost:5173 npx playwright test
 * The capture spec also needs PZ_OLD_URL (the old app on a scratch copy of its data) and PZ_CAPTURE_DIR.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PZ_BASE_URL ?? "http://localhost:5173",
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 900 } } }],
});
