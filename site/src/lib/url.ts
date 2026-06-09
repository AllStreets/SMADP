/**
 * Prefix an absolute-from-root path with Astro's `base` so internal links
 * keep working under the GitHub Pages subpath (`/SMADP/...`).
 *
 * Astro's `base` config is applied automatically to asset URLs (CSS, JS,
 * images Astro emits) but NOT to anchor hrefs you write yourself — so
 * every `<a href="/agents">` would 404 on the deployed site. Wrap every
 * internal href with this helper to fix that:
 *
 *     <a href={withBase('/agents')}>Agents</a>
 *
 * Pass-throughs:
 *   - empty / undefined → returned as-is
 *   - absolute URLs (https://, http://, //) → returned as-is
 *   - hash-only links (#foo) → returned as-is
 *   - already-prefixed paths (start with the base) → returned as-is
 */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '');

export function withBase(href: string | undefined | null): string {
  if (!href) return '';
  if (
    href.startsWith('http://') ||
    href.startsWith('https://') ||
    href.startsWith('//') ||
    href.startsWith('mailto:') ||
    href.startsWith('#')
  ) {
    return href;
  }
  if (!BASE) return href;
  if (href === BASE || href.startsWith(`${BASE}/`)) return href;
  if (href.startsWith('/')) return `${BASE}${href}`;
  return href;
}

export const BASE_URL = BASE;
