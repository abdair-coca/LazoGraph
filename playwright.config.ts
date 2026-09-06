import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    headless: true,
  },
  webServer: {
    command: "python -m lazograph.cli ui --port 8765 --no-browser",
    url: "http://127.0.0.1:8765/api/health",
    timeout: 20_000,
    reuseExistingServer: true,
  },
});
