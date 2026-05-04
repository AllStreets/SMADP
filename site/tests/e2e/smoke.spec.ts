import { test, expect } from '@playwright/test';

test.describe('SMADP frontend smoke', () => {
  test('home — persona switch hydrates the persona view', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/home');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Welcome to SMADP');
    await expect(page.locator('[data-persona-tiles]')).toBeVisible();

    // Pick the auditor tile
    await page.locator('[data-persona-pick="auditor"]').click();

    // Persona view becomes visible; the auditor's first panel (framework_coverage) link is present
    await expect(page.locator('[data-persona-view]')).toBeVisible();
    await expect(page.getByRole('link', { name: /Framework coverage/i })).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('frameworks index — links to deep view; deep view renders', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/frameworks');
    const firstFwLink = page.locator('h2 a[href^="/frameworks/"]').first();
    await expect(firstFwLink).toBeVisible();
    const href = await firstFwLink.getAttribute('href');
    expect(href).toBeTruthy();

    await page.goto(href!);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('static admin shells render without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    for (const path of ['/workspaces', '/refresh', '/webhooks', '/passports']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    }

    // Console may have fetch errors (no backend) — only fail on uncaught JS errors
    expect(errors).toEqual([]);
  });

  test('chains index → deep view renders', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      // The /chains page hydrates fresh chains from /api/chains; in static preview
      // the backend is offline, which surfaces as a console-logged network error.
      // Only fail on real JS errors, not expected fetch failures.
      const text = msg.text();
      if (msg.type() === 'error' && !text.includes('ERR_CONNECTION_REFUSED')) {
        errors.push(text);
      }
    });

    await page.goto('/chains');

    // Get the first chain link by finding h1 in main and using that context
    const firstChainLink = page.locator('main a[href^="/chains/c_"]').first();
    const href = await firstChainLink.getAttribute('href');
    expect(href).toBeTruthy();

    await page.goto(href!);
    await expect(page.locator('svg[aria-label="Chain topology"]')).toBeVisible();

    expect(errors).toEqual([]);
  });
});
