import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

/**
 * Vitest reads this file *instead of* vite.config.ts when both exist, so the
 * `@/*` alias is declared here too rather than inherited. Tailwind is
 * deliberately absent: `css: false` means the test runner never processes
 * stylesheets, so loading the Tailwind plugin would only cost startup time.
 */
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  test: {
    environment: 'jsdom',
    globals: true,
    // Registers the jest-dom matchers on Vitest's `expect` (no local setup
    // file needed — the package ships a Vitest-specific entrypoint).
    setupFiles: ['@testing-library/jest-dom/vitest'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // The dashboard is a pure function of (snapshot, events[]) — tests must not
    // leak state between cases.
    restoreMocks: true,
    clearMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
    // Bootstrap state: the suites live in other workstreams and land later.
    passWithNoTests: true,

    coverage: {
      // Requires `@vitest/coverage-v8`; only loaded when run with --coverage.
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.{test,spec}.{ts,tsx}',
        'src/**/*.d.ts',
        'src/main.tsx',
      ],
    },
  },
})
