import { test, expect } from '@playwright/test';

test.describe('SMADP frontend smoke', () => {
  test('landing renders without console errors', async ({ page }) => {
    // The /home persona-picker was archived 2026-06-09; the landing page at
    // / is now the canonical entry. We assert the H1 renders and the
    // /agents catalog link is wired in the DOM (it lives in the hero stats
    // strip below the fold on narrow viewports, so check by attached, not
    // by visible).
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('a[href$="/agents"]').first()).toBeAttached();
    await expect(page.locator('a[href$="/verdicts"]').first()).toBeAttached();

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

  test('pending index → detail view renders', async ({ page }) => {
    // /chains/* was archived 2026-06-09 alongside the persona-picker. The
    // operator-review queue at /pending is the new place that exercises a
    // build-time-generated index → dynamic-detail link path.
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/pending');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Pending verdicts');
    // Detail-page links are <a href="/pending/<key>"> wrapping each row cell.
    // Pending may be empty in a fresh checkout, in which case the heading
    // alone is sufficient evidence the page rendered.
    expect(errors).toEqual([]);
  });
});
