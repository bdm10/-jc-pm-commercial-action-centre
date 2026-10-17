import { defineConfig, devices } from "@playwright/test";

// E2E runs against the FastAPI server serving the built SPA (npm run build; see README).
// globalSetup re-seeds the synthetic demo database so every run starts from the same state.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
    locale: "es-ES",
    timezoneId: "Europe/Madrid",
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [
    { name: "phone", use: { ...devices["Pixel 7"], browserName: "chromium", viewport: { width: 390, height: 844 } } },
    { name: "desktop", use: { browserName: "chromium", viewport: { width: 1366, height: 900 } } },
  ],
});
