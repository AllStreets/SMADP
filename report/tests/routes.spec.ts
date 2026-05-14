import { test, expect } from '@playwright/test';

const routes = ['/', '/brief', '/prospectus', '/dossier'];

for (const route of routes) {
  test(`route ${route} renders without console errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    const response = await page.goto(route);
    expect(response?.status(), `HTTP status for ${route}`).toBe(200);
    await expect(page.locator('main')).toBeVisible();
    expect(errors, `console errors on ${route}`).toEqual([]);
  });
}

test('picker links to all three layouts', async ({ page }) => {
  await page.goto('/');
  const picker = page.locator('.picker-grid');
  for (const name of ['Brief', 'Prospectus', 'Dossier']) {
    await expect(picker.getByRole('link', { name: new RegExp(name) })).toBeVisible();
  }
});

test('Brief layout includes severity heatmap', async ({ page }) => {
  await page.goto('/brief');
  await expect(page.getByText(/Severity heatmap/)).toBeVisible();
});

test('Prospectus layout includes data appendix marker', async ({ page }) => {
  await page.goto('/prospectus');
  await expect(page.getByText(/Data appendix/)).toBeVisible();
});

test('Dossier layout lists every risk dimension', async ({ page }) => {
  await page.goto('/dossier');
  for (const letter of ['Risk A', 'Risk B', 'Risk C', 'Risk D', 'Risk E']) {
    await expect(page.getByText(letter, { exact: true }).first()).toBeVisible();
  }
});

test('Download PDF link is present on layout pages', async ({ page }) => {
  for (const route of ['/brief', '/prospectus', '/dossier']) {
    await page.goto(route);
    const link = page.getByRole('link', { name: /Download PDF/i });
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');
    expect(href).toBe(`${route}.pdf`);
    expect(await link.getAttribute('download')).toBeTruthy();
  }
});
