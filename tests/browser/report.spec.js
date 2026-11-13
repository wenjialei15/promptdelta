const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

async function screenshot(page, name) {
  if (!process.env.UPDATE_SCREENSHOTS) return;
  const directory = path.resolve(__dirname, '../../docs/images');
  await fs.mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, name) });
}

test('report shows demo counts, filtering and searchable outputs', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/report.html');
  await expect(page.locator('.case')).toHaveCount(6);
  await expect(page.locator('.banner')).toContainText('2 条退步');
  await expect(page.locator('#visible-count')).toHaveText('6');
  await expect(page.getByText('离线回放', { exact: false })).toBeVisible();
  await screenshot(page, 'report-desktop.png');
  await page.locator('#filter').selectOption('regression');
  await expect(page.locator('.case:visible')).toHaveCount(2);
  await page.locator('#search').fill('quantity');
  await expect(page.locator('.case:visible')).toHaveCount(1);
  await expect(page.locator('.case:visible h2')).toHaveText('order-extraction');
  await page.locator('#search').fill('nothing-matches-this');
  await expect(page.locator('#empty')).toBeVisible();
  await expect(page.locator('#visible-count')).toHaveText('0');
  expect(errors).toEqual([]);
});

test('assertion details explain the changed outcome', async ({ page }) => {
  await page.goto('/report.html');
  const card = page.locator('.case').filter({ has: page.getByRole('heading', { name: 'order-extraction', exact: true }) });
  const candidate = card.locator('.output').nth(1);
  await candidate.locator('summary').click();
  await expect(candidate.locator('li').filter({ hasText: '/quantity' })).toContainText('✕');
  await expect(candidate.locator('pre')).toContainText('"quantity":"2"');
});

test('mobile report has no page overflow and filters remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 950 });
  await page.goto('/report.html');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await screenshot(page, 'report-mobile.png');
  await page.locator('#filter').selectOption('improvement');
  await expect(page.locator('.case:visible')).toHaveCount(1);
  await expect(page.locator('.case:visible h2')).toHaveText('shipping-uncertainty');
});

test('report makes no external requests', async ({ page }) => {
  const external = [];
  page.on('request', (request) => {
    if (!request.url().startsWith('http://127.0.0.1:8766/')) external.push(request.url());
  });
  await page.goto('/report.html');
  await expect(page.locator('#visible-count')).toHaveText('6');
  await page.locator('#filter').selectOption('regression');
  expect(external).toEqual([]);
});
