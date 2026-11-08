#!/usr/bin/env node
// One headless pass over a cloud box's console: the login page loads, then signing in as a demo person through the dev
// sign-in lands on chat. The box's public address needs a Fly sign-in, and the organization token would replace the
// app's own Authorization header on every call. So the page is opened through a `sprite proxy` tunnel to the box's own
// port (BOX_TUNNEL, on localhost: Next's dev server refuses other origins), and the calls the page makes to the public
// address's /api/ routes are carried through the same tunnel.
//   BOX_TUNNEL=http://localhost:18081 node scripts/box-check.mjs https://ops-ai-box-1-xxxx.sprites.app
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const base = (process.argv[2] ?? '').replace(/\/+$/, '');
const tunnel = (process.env.BOX_TUNNEL ?? '').replace(/\/+$/, '');
if (!base || !tunnel) {
  console.error('usage: BOX_TUNNEL=http://localhost:<port> node scripts/box-check.mjs <box address>');
  process.exit(2);
}
const { chromium } = createRequire(join(ROOT, 'packages/usecase-runner/package.json'))('playwright');
const shots = join(ROOT, '.logs', 'box-check');
mkdirSync(shots, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
// The page is cross-origin to the public address here, so the browser's preflight is answered and its headers allowed.
const cors = (origin) => ({
  'access-control-allow-origin': origin,
  'access-control-allow-credentials': 'true',
  'access-control-allow-headers': '*',
  'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
});
await context.route(`${base}/**`, async (route) => {
  const request = route.request();
  const origin = request.headers().origin ?? tunnel;
  if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors(origin) });
  try {
    const response = await route.fetch({ url: tunnel + request.url().slice(base.length), maxRedirects: 0 });
    await route.fulfill({ response, headers: { ...response.headers(), ...cors(origin) } });
  } catch {
    // The page was closed while a call was in flight.
  }
});
const page = await context.newPage();
const failures = [];
const step = async (name, fn) => {
  const t = Date.now();
  try {
    const detail = await fn();
    console.log(`PASS ${name} (${((Date.now() - t) / 1000).toFixed(1)}s)${detail ? `: ${detail}` : ''}`);
  } catch (e) {
    failures.push(name);
    console.log(`FAIL ${name}: ${String(e.message).split('\n')[0]}`);
    await page.screenshot({ path: join(shots, 'failure.png') }).catch(() => {});
  }
};

await step('login page loads', async () => {
  const r = await page.goto(`${tunnel}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  if (!r || r.status() !== 200) throw new Error(`status ${r?.status()}`);
  await page.getByText('Welcome back').waitFor({ timeout: 90_000 });
  await page.screenshot({ path: join(shots, 'login.png') });
  return await page.title();
});
await step('dev sign-in lands on chat', async () => {
  await page.getByTestId('login-demo').click();
  const person = page.getByTestId('login-demo-person').first();
  await person.waitFor({ timeout: 30_000 });
  const who = (await person.innerText()).replace(/\s+/g, ' ');
  await person.click();
  await page.waitForURL(/\/chat/, { timeout: 120_000 });
  // Loading placeholders stay until the browser has reached the services through the box's address; the greeting does not.
  await page.getByText('Ask Ops Assistant anything').waitFor({ timeout: 120_000 });
  await page.screenshot({ path: join(shots, 'chat.png') });
  return `${who} at ${new URL(page.url()).pathname}`;
});

await context.unrouteAll({ behavior: 'ignoreErrors' });
await browser.close();
if (failures.length) process.exit(1);
