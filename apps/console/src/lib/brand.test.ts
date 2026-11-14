import assert from 'node:assert/strict';
import { test } from 'node:test';

import { brandStyle } from './brand.ts';

test('a brand colour from .env overrides the accent in light and dark', () => {
  assert.equal(brandStyle({ light: '#008a00' }), ':root{--primary:#008a00}.dark{--primary:#008a00}');
  assert.equal(brandStyle({ light: 'oklch(0.55 0.18 142)', dark: 'oklch(0.7 0.19 142)' }), ':root{--primary:oklch(0.55 0.18 142)}.dark{--primary:oklch(0.7 0.19 142)}');
  assert.equal(brandStyle({}), '');
});

test('a value that is not a colour is ignored, so it cannot break out of the style tag', () => {
  assert.equal(brandStyle({ light: 'red}</style><script>x</script>' }), '');
  assert.equal(brandStyle({ light: 'url(https://evil.example)' }), '');
});
