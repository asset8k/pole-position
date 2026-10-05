import { defineConfig, devices } from '@playwright/test';

const production = process.env.FRONTEND_PREVIEW === '1';
export default defineConfig({
  testDir: './tests/browser',
  outputDir: production ? './test-results/production' : './test-results/browser',
  testMatch: production ? '**/production.spec.ts' : '**/*.spec.ts',
  testIgnore: production ? [] : ['**/production.spec.ts'],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: production ? 'http://127.0.0.1:5174' : 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    // Optional installed-browser fallback; CI uses Playwright Chromium by default.
    channel: process.env.PLAYWRIGHT_CHANNEL,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: production ? 'npm run preview -- --port 5174 --strictPort' : 'npm run dev -- --port 5173 --strictPort',
    url: production ? 'http://127.0.0.1:5174' : 'http://127.0.0.1:5173',
    reuseExistingServer: !production && !process.env.CI,
  },
});
