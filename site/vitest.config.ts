import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['tests/lib/**/*.test.ts'],
    globals: false,
  },
});
