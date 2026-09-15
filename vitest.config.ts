import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/frontend/**/*.test.ts'],
    setupFiles: ['./tests/setup.ts'],
    reporters: ['default', 'junit'],
    outputFile: {
      junit: './test-results/junit.xml'
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'lcov', 'html'],
      reportsDirectory: './coverage',
      include: [
        'static/js/i18n.js',
        'static/js/shop.js',
        'static/js/advanced-search.js',
        'static/js/query-optimizer.js',
        'static/js/dark-mode.js',
        'static/js/lazy-loader.js',
        'static/js/error-reporter.js'
      ],
      thresholds: {
        lines: 97,
        functions: 97,
        branches: 98,
        statements: 97
      }
    }
  }
});