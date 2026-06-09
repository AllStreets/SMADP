/**
 * Astro integration: rewrite `href="/..."` and `src="/..."` in the built
 * HTML output so absolute-from-root links work under a deploy subpath like
 * `/SMADP/` on GitHub Pages.
 *
 * Astro's `base` config rewrites asset URLs Astro emits (CSS, JS) but does
 * NOT rewrite anchor hrefs you author yourself. Updating every component to
 * call a `withBase()` helper would touch dozens of files; doing the rewrite
 * once at the dist boundary is one place to maintain, catches future links
 * automatically, and runs only at deploy build (PAGES=1).
 *
 * Rewrites only paths that:
 *   - start with `/`
 *   - are not already prefixed with the base
 *   - are not `//`-style protocol-relative URLs
 *   - are not the base path itself (e.g. `/SMADP/`)
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';

async function walkHtml(dir) {
  const out = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...(await walkHtml(full)));
    } else if (entry.name.endsWith('.html')) {
      out.push(full);
    }
  }
  return out;
}

/**
 * @param {string} base - the deploy prefix, e.g. `/SMADP` (no trailing slash)
 */
export default function baseRewrite(base) {
  if (!base || base === '/') {
    // No-op integration if we're not on a subpath deploy.
    return { name: 'base-rewrite', hooks: {} };
  }
  const cleanBase = base.replace(/\/$/, '');
  // Match `href="/..."` or `src="/..."` where the value starts with `/` but
  // is NOT already `/SMADP/...`, `//...`, or just `/SMADP`.
  // We use a single regex so a path that appears multiple times in the same
  // line (multiple links per row) gets every instance touched.
  const re = new RegExp(
    `((?:\\s|^)(?:href|src)=")(/(?!${cleanBase.slice(1)}/|/))`,
    'g',
  );
  return {
    name: 'base-rewrite',
    hooks: {
      'astro:build:done': async ({ dir, logger }) => {
        const distDir = dir.pathname;
        const files = await walkHtml(distDir);
        let touched = 0;
        let rewrites = 0;
        for (const f of files) {
          const before = await fs.readFile(f, 'utf-8');
          let count = 0;
          const after = before.replace(re, (_, lead, slash) => {
            count++;
            return `${lead}${cleanBase}${slash}`;
          });
          if (count > 0) {
            await fs.writeFile(f, after);
            touched++;
            rewrites += count;
          }
        }
        logger.info(
          `base-rewrite: prefixed ${rewrites} href/src URL(s) with ${cleanBase} across ${touched} HTML files`,
        );
      },
    },
  };
}
