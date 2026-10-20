// Screenshots of a mailbox demo walk in a deployed console (docs/console/mailbox-demo.md, "On Fly staging"): the case,
// the Human Task and the run, headless through the use-case harness, and any 4xx/5xx or page error on each.
//   STG_ORIGIN=https://<your-app>-one.fly.dev STG_EMAIL=... STG_PASSWORD=... [STG_TEAM=<team id>] OUT=<dir> \
//   node deploy/fly/staging/mailbox_demo_shots.mjs cases/<case id> reviews/<run id>:review:1 workflows/runs/<run id>
// Exits with the number of pages that failed.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from '@ops-ai/usecase-runner/harness';

const origin = process.env.STG_ORIGIN;
const out = process.env.OUT ?? '.';
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
let bad = [];
let errors = [];
page.on('response', (r) => {
  if (r.status() >= 400 && r.url().startsWith(origin)) bad.push(`${r.status()} ${r.url().replace(origin, '').slice(0, 110)}`);
});
page.on('pageerror', (e) => errors.push(e.message.slice(0, 160)));

await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
await page.locator('#email').fill(process.env.STG_EMAIL);
await page.locator('#password').fill(process.env.STG_PASSWORD);
await page.keyboard.press('Enter');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).catch(() => {});
// The console keeps the chosen team for the tab in sessionStorage, as the team switcher does.
if (process.env.STG_TEAM) await page.evaluate((team) => sessionStorage.setItem('ops-team', team), process.env.STG_TEAM);

let failed = 0;
for (const path of process.argv.slice(2)) {
  bad = [];
  errors = [];
  await page.goto(`${origin}/${path}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const text = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ');
  const nf = /page not found|could not be found|not found/i.test(text);
  const file = join(out, `${path.split('/')[0]}-${path.split('/').pop().replace(/[^a-z0-9_-]/gi, '_')}.png`);
  await page.screenshot({ path: file, fullPage: true });
  const ok = !bad.length && !errors.length && !nf;
  if (!ok) failed += 1;
  console.log(`${ok ? 'OK  ' : 'FAIL'} /${path} -> ${file} | ${text.slice(0, 160)}${bad.length ? ' | ' + [...new Set(bad)].join(', ') : ''}${errors.length ? ' | js: ' + errors[0] : ''}`);
}
await browser.close();
process.exit(failed);
