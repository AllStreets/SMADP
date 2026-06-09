import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  retries: 0,
  webServer: {
    command: 'pnpm preview --port 4321',
    url: 'http://localhost:4321',
    reuseExistingServer: true,
    timeout: 60_000
  },
  use: {
    baseURL: 'http://localhost:4321',
    screenshot: 'only-on-failure'
  }
});
