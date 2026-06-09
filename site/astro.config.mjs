import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// https://astro.build/config
//
// GitHub Pages serves this site at https://allstreets.github.io/SMADP/, so
// asset URLs need the `/SMADP` prefix. The deploy workflow sets PAGES=1 to
// flip both `site` and `base` to the Pages target. Local `astro dev` still
// serves at /.
const PAGES = process.env.PAGES === '1';

export default defineConfig({
  site: PAGES ? 'https://allstreets.github.io' : 'https://smadp.dev',
  base: PAGES ? '/SMADP' : '/',
  output: 'static',
  trailingSlash: 'ignore',
  devToolbar: {
    enabled: false,
  },
  integrations: [
    tailwind({ applyBaseStyles: false }),
  ],
  vite: {
    server: {
      fs: {
        // Allow loading the catalog/ directory at the repo root.
        allow: ['..'],
      },
    },
  },
});
