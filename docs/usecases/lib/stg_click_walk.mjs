// Signs in to a deployed console and clicks through it the way a person does: every sidebar link, then the first
// row link on each list page. Reports every 4xx/5xx response (pages, RSC payloads and API calls), page errors and any
// "not found" text, per click. STG_ORIGIN, STG_EMAIL and STG_PASSWORD come from the environment.
import { chromium } from '@ops-ai/usecase-runner/harness';

const origin = process.env.STG_ORIGIN;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
let bad = [];
let errors = [];
page.on('response', (r) => {
  if (r.status() >= 400 && r.url().startsWith(origin)) bad.push(`${r.status()} ${r.url().replace(origin, '').slice(0, 110)}`);
});
page.on('pageerror', (e) => errors.push(e.message.slice(0, 120)));

await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
await page.locator('#email').fill(process.env.STG_EMAIL);
await page.locator('#password').fill(process.env.STG_PASSWORD);
await page.keyboard.press('Enter');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).catch(() => {});

async function report(label) {
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
  const text = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
  const nf = /page not found|this page could not be found|404/i.test(text);
  const ok = !bad.length && !errors.length && !nf;
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label} -> ${page.url().replace(origin, '')}${nf ? ' | NOT FOUND text' : ''}${bad.length ? ' | ' + [...new Set(bad)].slice(0, 4).join(', ') : ''}${errors.length ? ' | js: ' + errors[0] : ''}`);
  bad = [];
  errors = [];
}

// The shell renders only once the person's team is known (the session gate), so wait for the sidebar before reading it.
await page.locator('[data-sidebar="sidebar"] a[href^="/"]').first().waitFor({ timeout: 30_000 }).catch(() => {});
const links = await page.locator('[data-sidebar="sidebar"] a[href^="/"], nav a[href^="/"]').evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute('href')))]);
for (const href of links) {
  await page.locator(`[data-sidebar="sidebar"] a[href="${href}"]`).first().click({ timeout: 10_000 });
  // networkidle resolves before Next's client router updates the URL, so wait for the URL itself.
  const arrived = await page.waitForURL((u) => u.pathname + u.search === href, { timeout: 15_000 }).then(() => true, () => false);
  if (!arrived) bad.push(`STUCK on ${page.url().replace(origin, '')}`);
  await report(`nav ${href}`);
  // The URL changes before a list's rows arrive, so wait for the first row before deciding the page has none.
  const row = page.locator('main table tbody tr a[href^="/"], main [role="row"] a[href^="/"]').first();
  await row.waitFor({ timeout: 8_000 }).catch(() => {});
  if (await row.count()) {
    const to = await row.getAttribute('href');
    await row.click({ timeout: 10_000 }).catch(() => {});
    const there = await page.waitForURL((u) => u.pathname + u.search === to, { timeout: 15_000 }).then(() => true, () => false);
    if (!there) bad.push(`STUCK on ${page.url().replace(origin, '')}`);
    await report(`  row ${to}`);
    // Back on the list, so the next sidebar click starts from where a person would be.
    await page.goBack({ waitUntil: 'domcontentloaded' }).catch(() => {});
  }
}
await browser.close();
