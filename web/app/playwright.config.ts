import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:3100',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'npx tsx tests/e2e/mock-server.ts',
      port: 8010,
      reuseExistingServer: false,
      timeout: 15000,
    },
    {
      command: 'npm run dev -- --port 3100',
      port: 3100,
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        API_BASE_URL: 'http://127.0.0.1:8010',
        NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8010',
      },
    },
  ],
});
