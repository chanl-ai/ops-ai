// Signs in to a deployed console and opens every nav page, reporting page errors, failed API calls and error text.
// STG_ORIGIN, STG_EMAIL and STG_PASSWORD come from the environment; nothing secret is printed.
import { chromium } from '@ops-ai/usecase-runner/harness';

const origin = process.env.STG_ORIGIN;
const pages = (process.env.STG_PAGES || '/').split(' ');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
await page.locator('#email').fill(process.env.STG_EMAIL);
await page.locator('#password').fill(process.env.STG_PASSWORD);
await page.keyboard.press('Enter');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).catch(() => {});
console.log('signed in:', !page.url().includes('/login'));

for (const p of pages) {
  const errors = [];
  const failed = [];
  const onErr = (e) => errors.push(e.message.slice(0, 120));
  const onResp = (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) failed.push(`${r.status()} ${new URL(r.url()).pathname}`);
  };
  page.on('pageerror', onErr);
  page.on('response', onResp);
  await page.goto(`${origin}${p}`, { waitUntil: 'networkidle', timeout: 60_000 }).catch((e) => errors.push(`goto ${e.message.slice(0, 80)}`));
  const text = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ');
  const bad = text.match(/(something went wrong|failed to load|could not load|not found|error[: ][^.]{0,60})/i);
  page.off('pageerror', onErr);
  page.off('response', onResp);
  const ok = !errors.length && !failed.length && !bad;
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${p}${failed.length ? ' | api: ' + [...new Set(failed)].join(', ') : ''}${errors.length ? ' | js: ' + errors[0] : ''}${bad ? ' | text: ' + bad[0] : ''}`);
}
await browser.close();
