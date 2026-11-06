import { describe, expect, it } from 'vitest';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const sourceRoot = resolve(process.cwd(), 'src');

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : [path];
  });
}

describe('frontend API wiring', () => {
  it('does not contain the legacy JSX app or fixture module', () => {
    expect(existsSync(join(sourceRoot, 'App.jsx'))).toBe(false);
    expect(existsSync(join(sourceRoot, 'fixtures.js'))).toBe(false);
  });

  it('keeps host-specific URLs and direct fetch calls inside api.js', () => {
    const violations = sourceFiles(sourceRoot)
      .filter((path) => !path.endsWith('.test.ts') && !path.endsWith('.test.tsx'))
      .filter((path) => relative(sourceRoot, path).replaceAll('\\', '/') !== 'api.js')
      .filter((path) => {
        const content = readFileSync(path, 'utf8');
        return /localhost|fetch\s*\(/.test(content);
      });
    expect(violations).toEqual([]);
  });
});
