// Every icon the sidebar names exists in lucide-react; src/lib/source.ts throws on an unknown one, but only in `next build`.
import { icons } from 'lucide-react';
import { SITE } from '../src/lib/nav.mjs';

const names = new Set();
JSON.stringify(SITE, (k, v) => (k === 'icon' && typeof v === 'string' && names.add(v), v));
const pascal = (n) => n.replace(/(^|-)(\w)/g, (_, __, c) => c.toUpperCase());
const missing = [...names].filter((n) => !icons[pascal(n)]);
if (missing.length) {
  console.error(`check-icons: no lucide icon named ${missing.map((n) => `"${n}"`).join(', ')} (apps/docs/src/lib/nav.mjs)`);
  process.exit(1);
}
console.log(`check-icons: ${names.size} sidebar icons exist`);
