// The embed app's bundle carries none of the console's API client (c-158): `@/lib/api` must resolve to the widget
// client, or the embedded chat would call console routes. Builds the app, then looks for strings only the console's
// client and its mock hold. Run: pnpm --filter @ops-ai/embed check:bundle
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { join } from 'node:path';

const APP = new URL('..', import.meta.url).pathname;
const DIST = process.env.OPS_EMBED_DIST_DIR || '.next-bundle-check';

// Each marker sits in exactly one console file the embed must never load.
const MARKERS = [
  ['/chat/agents', 'the console chat client (src/lib/api/chat-http.ts)'],
  ['northfield-demo', "the console mock's sign-in seed (src/lib/api/mock/auth/seed.ts)"],
  ['REV-3020', "the console mock's fixtures (src/lib/api/mock/fixtures.ts)"],
];

if (!process.argv.includes('--no-build')) {
  // Tailwind scans the app folder for class names, a previous build's output included, and fails on the minified JS.
  rmSync(join(APP, DIST), { recursive: true, force: true });
  execFileSync('pnpm', ['exec', 'next', 'build'], { cwd: APP, stdio: 'inherit', env: { ...process.env, OPS_EMBED_DIST_DIR: DIST } });
}

const files = [];
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (path.endsWith('.js')) files.push(path);
  }
};
walk(join(APP, DIST, 'static'));
walk(join(APP, DIST, 'server'));

const found = [];
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  for (const [marker, source] of MARKERS) if (text.includes(marker)) found.push(`${file.slice(APP.length)}: "${marker}" from ${source}`);
}
if (found.length) {
  console.error(`check-bundle: the console's API client reached the embed bundle:\n  ${found.join('\n  ')}`);
  process.exit(1);
}
console.log(`check-bundle: ${files.length} files, none carries the console's API client or mock`);
