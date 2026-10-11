import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

/**
 * ESLint 10 flat config for the dashboard.
 *
 * Type-aware linting is on (`projectService: true`), which is what makes rules
 * like `no-floating-promises` and `no-misused-promises` possible — both matter
 * for a UI driven by a WebSocket event stream, where a dropped promise is a
 * silently missed event. The project service reuses the same tsconfig.json that
 * `npm run typecheck` uses, so there is no second source of truth for which
 * files are part of the program.
 */
export default tseslint.config(
  {
    name: 'historiador/ignores',
    ignores: ['dist/**', 'coverage/**', 'node_modules/**'],
  },

  // This config file is plain JS and is not part of the TS program, so it is
  // linted without type information.
  {
    name: 'historiador/eslint-config-file',
    files: ['eslint.config.js'],
    extends: [js.configs.recommended],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: globals.node,
    },
  },

  {
    name: 'historiador/typescript',
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommendedTypeChecked,
      tseslint.configs.stylisticTypeChecked,
    ],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // `verbatimModuleSyntax` is on in tsconfig, so type-only imports must be
      // marked as such or the build breaks. Enforce it here rather than
      // discovering it at build time.
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
      // `_`-prefixed bindings are the agreed opt-out for intentionally unused
      // params (e.g. reducer signatures that ignore an argument).
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // ARCHITECTURE.md §10: no swallowed errors, no unexplained `any`.
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/switch-exhaustiveness-check': 'error',
    },
  },

  // Build + test tooling executes in Node, not the browser.
  {
    name: 'historiador/tooling',
    files: ['vite.config.ts', 'vitest.config.ts'],
    languageOptions: { globals: globals.node },
  },

  {
    name: 'historiador/react',
    files: ['**/*.tsx'],
    extends: [reactHooks.configs.flat.recommended, reactRefresh.configs.vite],
  },
)
