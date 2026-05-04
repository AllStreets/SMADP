import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.SMADP_SITE_BASE ?? 'http://localhost:4321',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
});
