import path from 'node:path';

import js from '@eslint/js';
import { configs, plugins } from 'eslint-config-airbnb-extended';
import globals from 'globals';

const off = 'off';
const warn = 'warn';
const error = 'error';

const { dirname } = import.meta;

const listOfRules = {
  a11y: {
    'jsx-a11y/anchor-is-valid': [warn, { aspects: ['invalidHref'] }],
    'jsx-a11y/click-events-have-key-events': off,
    'jsx-a11y/control-has-associated-label': off,
    'jsx-a11y/label-has-associated-control': off,
    'jsx-a11y/label-has-for': off,
    'jsx-a11y/no-autofocus': off,
    'jsx-a11y/no-static-element-interactions': off,
  },
  import: {
    'import-x/extensions': [error],
    'import-x/no-cycle': off,
    'import-x/no-extraneous-dependencies': [error, { devDependencies: ['vite.config.js', '**/*.config.js'] }],
    'import-x/no-named-as-default': off,
    'import-x/no-rename-default': off,
    'import-x/no-unresolved': [error],
    'import-x/prefer-default-export': off,
  },
  misc: {
    '@stylistic/brace-style': [error, '1tbs', { allowSingleLine: true }],
    '@stylistic/comma-dangle': [error, 'always-multiline'],
    '@stylistic/max-len': off,
    '@stylistic/max-statements-per-line': off,
    '@stylistic/no-confusing-arrow': off,
    '@stylistic/object-curly-newline': [error, { ObjectPattern: { minProperties: 6 } }],
    'no-console': off,
    'no-nested-ternary': off,
    'no-shadow': error,
    'no-unused-vars': [error, { caughtErrors: 'none' }],
    'no-use-before-define': off,
    'no-underscore-dangle': off,
    camelcase: [error],
  },
  react: {
    'react-hooks/exhaustive-deps': warn,
    'react-hooks/refs': off,
    'react-hooks/rules-of-hooks': error,
    'react-hooks/set-state-in-effect': off,
    'react/destructuring-assignment': off,
    'react/forbid-prop-types': off,
    'react/jsx-filename-extension': off,
    'react/jsx-newline': [error, { prevent: false }],
    'react/jsx-no-duplicate-props': [error, { ignoreCase: false }],
    'react/jsx-no-useless-fragment': error,
    'react/jsx-props-no-spreading': off,
    'react/no-access-state-in-setstate': off,
    'react/no-array-index-key': off,
    'react/prop-types': off,
    'react/require-default-props': off,
    'react/state-in-constructor': off,
    'react/static-property-placement': off,
    'react/react-in-jsx-scope': off,
    'react/jsx-sort-props': [error, {
      callbacksLast: false,
      shorthandFirst: false,
      shorthandLast: false,
      ignoreCase: true,
      noSortAlphabetically: false,
      reservedFirst: ['key'],
    }],
    'no-param-reassign': [error, { props: true, ignorePropertyModificationsFor: ['state', 'draft'] }],
    'react/no-unstable-nested-components': [off],
  },
};

const rules = {
  ...listOfRules.import,
  ...listOfRules.a11y,
  ...listOfRules.misc,
  ...listOfRules.react,
};

export default [
  { ignores: ['dist', 'eslint.config.js', '**/*.d.ts'] },

  plugins.stylistic,
  plugins.importX,
  plugins.react,
  plugins.reactA11y,
  plugins.reactHooks,

  ...configs.base.recommended,
  ...configs.react.recommended,
  js.configs.recommended,

  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
      // airbnb-extended pins parserOptions.ecmaVersion to 2018, which overrides languageOptions.ecmaVersion
      parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } },
    },

    rules,

    settings: {
      // airbnb-extended sets resolver-next, which makes import-x skip legacy resolvers (alias)
      'import-x/resolver-next': false,
      'import-x/resolver': {
        alias: {
          map: [
            ['@Api', path.resolve(dirname, './src/api')],
            ['@Components', path.resolve(dirname, './src/components')],
            ['@Container', path.resolve(dirname, './src/container')],
            ['@Helpers', path.resolve(dirname, './src/helpers')],
            ['@Hooks', path.resolve(dirname, './src/hooks')],
            ['@Img', path.resolve(dirname, './src/resources/images')],
            ['@Modals', path.resolve(dirname, './src/components/modals')],
            ['@Src', path.resolve(dirname, './src')],
            ['@State', path.resolve(dirname, './src/store/state')],
            ['@Store', path.resolve(dirname, './src/store')],
            ['@Styles', path.resolve(dirname, './src/styles')],
          ],
          extensions: ['.js', '.jsx', '.json'],
        },
      },
    },
  },
];
