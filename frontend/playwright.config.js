import { defineConfig, devices } from '@playwright/test';

const origin = 'http://127.0.0.1:4175';
const apiOrigin = 'http://127.0.0.1:4176';
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  use: {
    ...devices['Pixel 5'],
    baseURL: origin,
    trace: 'retain-on-failure',
    launchOptions: executablePath ? { executablePath } : undefined,
  },
  projects: [
    { name: 'navegador-mobile-demo', testMatch: /demo\.spec\.js/ },
    { name: 'cliente-http-mobile', testMatch: /http\.spec\.js/, use: { baseURL: apiOrigin } },
  ],
  webServer: [
    { command: 'npm run dev -- --host 127.0.0.1 --port 4175 --strictPort', url: origin, env: { VITE_API_MODE: 'mock' } },
    { command: 'npm run dev -- --host 127.0.0.1 --port 4176 --strictPort', url: apiOrigin,
      env: { VITE_API_MODE: 'rest', VITE_API_BASE_URL: '/api/v1' } },
  ],
});
