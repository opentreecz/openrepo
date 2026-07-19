import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  // typescript-eslint's base config sets languageOptions.parser globally
  // (unscoped by `files`), so it must come before eslint-plugin-vue's
  // config or it clobbers vue-eslint-parser for .vue files.
  ...tseslint.configs.recommended,
  // "essential" (not "recommended"/"strongly-recommended") catches real
  // Vue mistakes without demanding this pre-existing codebase be
  // reformatted to the plugin's opinionated style rules.
  ...vue.configs['flat/essential'],
  {
    languageOptions: {
      globals: {
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        navigator: 'readonly',
        localStorage: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        FormData: 'readonly',
        fetch: 'readonly',
        File: 'readonly',
        Event: 'readonly',
        DragEvent: 'readonly',
        HTMLInputElement: 'readonly',
      },
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    files: ['**/*.vue', '**/*.ts'],
    rules: {
      // The existing codebase predates strict typing; start permissive
      // and tighten once the baseline is clean.
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'warn',
      'vue/multi-word-component-names': 'off',
      'vue/no-unused-vars': 'warn',
    },
  },
]
