import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import baseRewrite from './astro-base-rewrite.mjs';

// https://astro.build/config
//
// GitHub Pages serves this site at https://allstreets.github.io/SMADP/, so
// asset URLs need the `/SMADP` prefix. The deploy workflow sets PAGES=1 to
// flip both `site` and `base` to the Pages target. Local `astro dev` still
// serves at /. The baseRewrite integration walks the built HTML and
// rewrites every `href="/..."`/`src="/..."` to include the base — fixes
// anchor links that Astro doesn't auto-prefix.
const PAGES = process.env.PAGES === '1';
const BASE = PAGES ? '/SMADP' : '/';

export default defineConfig({
  site: PAGES ? 'https://allstreets.github.io' : 'https://smadp.dev',
  base: BASE,
  output: 'static',
  trailingSlash: 'ignore',
  devToolbar: {
    enabled: false,
  },
  integrations: [tailwind({ applyBaseStyles: false }), baseRewrite(BASE)],
  vite: {
    server: {
      fs: {
        // Allow loading the catalog/ directory at the repo root.
        allow: ['..'],
      },
    },
  },
});
