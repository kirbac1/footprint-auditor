import { defineConfig, devices } from "@playwright/test";

// End-to-end tests start the real API (serve runs the migrations) on a
// throwaway SQLite file, with demo scans and verification codes written to
// an outbox file the tests read. The frontend must be built first (npm run build).
const PORT = 8123;

const serverEnv: Record<string, string> = {
  EA_ENV: "dev",
  EA_DATABASE_URL: "sqlite+aiosqlite:///./e2e.db",
  EA_JWT_SECRET: "e2e-only-not-a-secret-e2e-only-not-a-secret",
  EA_FIELD_ENCRYPTION_KEY: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  EA_BLIND_INDEX_KEY: "e2e-only-blind-index-key",
  EA_DEMO_SCANS: "true",
      // Instant and identical every run; the agent itself is covered by the evals.
      EA_DEMO_SCRIPTED_MODEL: "true",
  EA_VERIFICATION_DELIVERY: "outbox",
  EA_OUTBOX_PATH: "e2e-outbox.jsonl",
  EA_SCAN_EXECUTION: "inline",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: "en-US",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `rm -f e2e.db e2e-outbox.jsonl && uv run exposure-auditor serve --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { ...(process.env as Record<string, string>), ...serverEnv },
  },
});
