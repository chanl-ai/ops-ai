#!/usr/bin/env node
// One headless pass over a cloud box through its public address, as a person with the link would use it:
// 1 the box refuses a visitor without the cookie, 2 the one-time link sets the cookie and lands on /login,
// 3 a demo sign-in lands on chat and stays there, 4 an API call with the app's own token answers 200.
//   BOX_KEY=<key> node scripts/box-check.mjs https://ops-ai-box-1-xxxx.sprites.app
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const base = (process.argv[2] ?? '').replace(/\/+$/, '');
const key = process.env.BOX_KEY ?? '';
if (!base || !key) {
  console.error('usage: BOX_KEY=<key> node scripts/box-check.mjs <box address>');
  process.exit(2);
}
const { chromium } = createRequire(join(ROOT, 'packages/usecase-runner/package.json'))('playwright');
const shots = join(ROOT, '.logs', 'box-check');
mkdirSync(shots, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();
// The app's token is read off its own calls, so step 4 uses exactly what the console sends.
let appAuth = '';
page.on('request', (r) => {
  const h = r.headers().authorization;
  if (h && r.url().startsWith(`${base}/api/platform/`)) appAuth = h;
});
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

await step('no cookie gets 403', async () => {
  const r = await fetch(`${base}/login`, { redirect: 'manual' });
  if (r.status !== 403) throw new Error(`status ${r.status}`);
  const k = await fetch(`${base}/__box?key=wrong`, { redirect: 'manual' });
  if (k.status !== 403) throw new Error(`wrong key answered ${k.status}`);
  return '/login 403, wrong key 403';
});
await step('link sets the cookie and lands on login', async () => {
  const r = await page.goto(`${base}/__box?key=${key}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  if (!r || r.status() !== 200) throw new Error(`status ${r?.status()}`);
  await page.waitForURL(/\/login/, { timeout: 30_000 });
  const c = (await context.cookies(base)).find((x) => x.name === 'ops_box');
  if (!c || !c.httpOnly || !c.secure) throw new Error('cookie ops_box missing or not HttpOnly and Secure');
  await page.getByText('Welcome back').waitFor({ timeout: 90_000 });
  await page.screenshot({ path: join(shots, 'login.png') });
  return 'ops_box set, HttpOnly, Secure';
});
await step('demo sign-in stays on chat for 10 seconds', async () => {
  await page.getByTestId('login-demo').click();
  const person = page.getByTestId('login-demo-person').first();
  await person.waitFor({ timeout: 30_000 });
  const who = (await person.innerText()).replace(/\s+/g, ' ');
  await person.click();
  await page.waitForURL(/\/chat/, { timeout: 120_000 });
  await page.getByText('Ask Ops Assistant anything').waitFor({ timeout: 120_000 });
  await page.waitForTimeout(10_000);
  if (!/\/chat/.test(new URL(page.url()).pathname)) throw new Error(`bounced to ${new URL(page.url()).pathname}`);
  await page.screenshot({ path: join(shots, 'chat.png') });
  return `${who} at ${new URL(page.url()).pathname}`;
});
await step('API call with the app token answers 200', async () => {
  if (!appAuth) throw new Error('the console sent no Authorization header');
  const r = await context.request.get(`${base}/api/platform/v1/teams`, { headers: { authorization: appAuth } });
  if (r.status() !== 200) throw new Error(`status ${r.status()}`);
  return 'GET /api/platform/v1/teams 200';
});

await browser.close();
if (failures.length) process.exit(1);
