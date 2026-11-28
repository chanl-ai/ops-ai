import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

// A settings page shows the "Sample data" banner and the Preview tag when it says it is sample, or, when it says
// nothing, when the route table in lib/api/index.ts gives its path no entry of its own. It then falls to the table's
// catch-all `/settings` entry, which is not served, and a live page carries a false banner above real rows. Each page
// must say which it is (`sample={...}` on SettingsPageLayout, `preview={...}` on PageLayout) unless an entry of the
// table names its path; an entry marked not served is a page the table knows is sample.
// Mock reads still mark a page sample at run time whatever it says, so `sample={false}` cannot hide sample data.

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', '..');

function pages(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return pages(path);
    return name === 'page.tsx' ? [path] : [];
  });
}

/** The route table's prefixes, each served or not: `served: false` is not served; any expression counts as served,
 * since every service is configured on a full stack. */
function areas(): { prefix: string; served: boolean }[] {
  const text = readFileSync(join(src, 'lib', 'api', 'index.ts'), 'utf8');
  return [...text.matchAll(/\{ prefix: '([^']+)', served: ([^}]+?) \}/g)].map((m) => ({ prefix: m[1]!, served: m[2]!.trim() !== 'false' }));
}

function routeOf(file: string): string {
  return `/${relative(join(src, 'app'), dirname(file)).split('/').join('/')}`;
}

test('no settings page falls to the catch-all route and shows the sample banner without saying it is sample', () => {
  const table = areas();
  const under = (route: string, prefix: string) => route === prefix || route.startsWith(`${prefix}/`);
  const guessed = (route: string) => table.filter((a) => under(route, a.prefix)).sort((x, y) => y.prefix.length - x.prefix.length)[0];
  const falseBanner = pages(here)
    .filter((file) => {
      const text = readFileSync(file, 'utf8');
      if (!/<(SettingsPageLayout|PageLayout)\b/.test(text)) return false;
      if (/<SettingsPageLayout\b[^>]*\bsample[=\s>]/s.test(text) || /<PageLayout\b[^>]*\bpreview=/s.test(text)) return false;
      return guessed(routeOf(file))?.prefix === '/settings';
    })
    .map(routeOf)
    .sort();
  assert.deepEqual(falseBanner, [], `these settings pages fall to the catch-all /settings route and show the sample banner: ${falseBanner.join(', ')}`);
});
