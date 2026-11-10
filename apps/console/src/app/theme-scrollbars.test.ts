import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const css = readFileSync(new URL('./globals.css', import.meta.url), 'utf8');

/** Body of the first top-level rule whose selector is exactly `selector`. */
function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  assert.notEqual(start, -1, `globals.css has no ${selector} rule`);
  return css.slice(start, css.indexOf('\n}', start));
}

// Without color-scheme the browser cannot tell which palette the page uses, so Windows Chrome and Edge draw scrollbars
// from the OS theme.
test('light theme declares color-scheme: light', () => {
  assert.match(rule(':root'), /color-scheme:\s*light\s*;/);
});

test('dark theme declares color-scheme: dark', () => {
  assert.match(rule('.dark'), /color-scheme:\s*dark\s*;/);
});

test('scrollbars are thin and take their colour from a theme token', () => {
  assert.match(rule('*'), /scrollbar-width:\s*thin\s*;/);
  assert.match(rule('html'), /scrollbar-color:[^;]*var\(--[\w-]+\)[^;]*;/);
});
