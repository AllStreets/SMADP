import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// https://astro.build/config
export default defineConfig({
  site: 'https://smadp.dev',
  output: 'static',
  trailingSlash: 'ignore',
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
