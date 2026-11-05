import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx,js}'],
    plugins: { 'react-hooks': reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
);
