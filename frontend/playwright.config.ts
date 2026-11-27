import { defineConfig } from '@playwright/test';

export default defineConfig({
    outputDir: './test-results/frontend',
    testDir: './tests',
    testIgnore: '**/docs/**',
    fullyParallel: false,
    workers: 1,
    retries: 0,
    use: {
        baseURL: process.env.E2E_LIVE_BASE_URL || 'http://127.0.0.1:4173',
        locale: 'en-US',
        trace: 'retain-on-failure',
        launchOptions: {
            executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
            args: ['--enable-unsafe-swiftshader'],
        },
    },
    webServer: process.env.E2E_LIVE_BASE_URL
        ? undefined
        : {
              command: 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
              url: 'http://127.0.0.1:4173',
              reuseExistingServer: false,
          },
});
