
import { defineConfig, devices } from "@playwright/test";

const FRONTEND_URL = process.env.FRONTEND_URL || "https://archmorphai.com";
const CI_BROWSER_CHANNEL = process.env.CI ? "chrome" : undefined;
const CI_VIDEO_MODE = process.env.CI ? "off" : "retain-on-failure";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 4 : undefined,
  maxFailures: process.env.CI ? 10 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  use: {
    baseURL: FRONTEND_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: CI_VIDEO_MODE,
  },
  projects: [
    {
      name: "chromium",
      grepInvert: /@mobile/,
      use: { ...devices["Desktop Chrome"], channel: CI_BROWSER_CHANNEL },
    },
    {
      name: "mobile-chrome",
      grep: /@mobile/,
      use: { ...devices["Pixel 5"], channel: CI_BROWSER_CHANNEL },
    },
  ],
});
