import { test, expect } from '@playwright/test';

const routes = ['/', '/briefs', '/primer', '/prospectus', '/dossier', '/references', '/search'];

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

test('Briefs index links to all three layouts', async ({ page }) => {
  await page.goto('/briefs');
  const list = page.locator('.briefs-list');
  for (const name of ['Primer', 'Prospectus', 'Dossier']) {
    await expect(list.getByRole('link', { name: new RegExp(`Open the ${name}`) }).first()).toBeVisible();
  }
});

test('Primer layout includes severity heatmap', async ({ page }) => {
  await page.goto('/primer');
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

test('References page surfaces evidence + framework + upstream sections', async ({ page }) => {
  await page.goto('/references');
  await expect(page.getByText(/Evidence bundles/).first()).toBeVisible();
  await expect(page.getByText(/Profile-field citations/).first()).toBeVisible();
  await expect(page.getByText(/Framework mappings/).first()).toBeVisible();
  await expect(page.getByText(/Upstream projects/).first()).toBeVisible();
});

test('Search page renders filter UI and verdict cards', async ({ page }) => {
  await page.goto('/search');
  await expect(page.locator('#search-q')).toBeVisible();
  await expect(page.locator('.sv-card').first()).toBeVisible();
});

test('Download PDF link is present on layout pages', async ({ page }) => {
  for (const route of ['/primer', '/prospectus', '/dossier']) {
    await page.goto(route);
    const link = page.getByRole('link', { name: /Download PDF/i });
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');
    expect(href).toBe(`${route}.pdf`);
    expect(await link.getAttribute('download')).toBeTruthy();
  }
});
