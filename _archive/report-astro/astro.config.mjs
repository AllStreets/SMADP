import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://smadp.local',
  output: 'static',
  build: {
    inlineStylesheets: 'auto'
  },
  vite: {
    server: { fs: { allow: ['..'] } }
  }
});
