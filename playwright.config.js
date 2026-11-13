const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/browser',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8766',
    viewport: { width: 1440, height: 1050 },
    locale: 'zh-CN',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python -m promptdelta demo --out reports/browser && python -m http.server 8766 --bind 127.0.0.1 --directory reports/browser',
    url: 'http://127.0.0.1:8766/report.html',
    reuseExistingServer: false,
  },
});
