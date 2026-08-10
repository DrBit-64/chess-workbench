import { existsSync } from 'node:fs';

import { defineConfig } from '@playwright/test';

const baseURL =
  process.env.CHESS_WORKBENCH_E2E_BASE_URL ?? 'http://127.0.0.1:15173';
const requestedExecutable = process.env.CHESS_WORKBENCH_E2E_CHROMIUM;
const executablePath = requestedExecutable
  ? requestedExecutable
  : existsSync('/snap/bin/chromium')
    ? '/snap/bin/chromium'
    : undefined;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 8_000 },
  outputDir: '../.cache/playwright/results',
  reporter: [
    ['line'],
    ['html', { outputFolder: '../.cache/playwright/report', open: 'never' }],
  ],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Trace and screenshots are sufficient diagnostics and keep the gate usable
    // with a system Chromium installation (no separate Playwright ffmpeg download).
    video: 'off',
    launchOptions: {
      ...(executablePath ? { executablePath } : {}),
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    },
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
