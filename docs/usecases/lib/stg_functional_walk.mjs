// Uses a deployed console the way a person checks a release: a chat turn that gets an answer, a workflow test run
// that reaches an outcome, and every Settings page. The click walk (stg_click_walk.mjs) proves pages open; this proves
// the three things people do most still work. Reports OK or FAIL per check with the 4xx/5xx and page errors seen.
// STG_ORIGIN, STG_EMAIL and STG_PASSWORD come from the environment.
import { chromium } from '@ops-ai/usecase-runner/harness';

const origin = process.env.STG_ORIGIN;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
let bad = [];
let errors = [];
let failed = 0;
page.on('response', (r) => {
  if (r.status() >= 400 && r.url().startsWith(origin)) bad.push(`${r.status()} ${r.url().replace(origin, '').slice(0, 100)}`);
});
page.on('pageerror', (e) => errors.push(e.message.slice(0, 120)));

function report(label, ok, detail = '') {
  const clean = ok && !bad.length && !errors.length;
  if (!clean) failed++;
  const extra = [detail, bad.length ? [...new Set(bad)].slice(0, 4).join(', ') : '', errors.length ? `js: ${errors[0]}` : '']
    .filter(Boolean)
    .join(' | ');
  console.log(`${clean ? 'OK  ' : 'FAIL'} ${label}${extra ? ' | ' + extra : ''}`);
  bad = [];
  errors = [];
}
const settle = () => page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});

await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
await page.locator('#email').fill(process.env.STG_EMAIL);
await page.locator('#password').fill(process.env.STG_PASSWORD);
await page.keyboard.press('Enter');
const signedIn = await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).then(() => true, () => false);
report('sign in', signedIn, page.url().replace(origin, ''));

// Chat: a new chat, one question, an answer that finishes without the failed marker or a refused model call.
await page.goto(`${origin}/chat`, { waitUntil: 'domcontentloaded' });
await settle();
const box = page.locator('main textarea').first();
const hasBox = await box.waitFor({ timeout: 20_000 }).then(() => true, () => false);
if (hasBox) {
  const before = (await page.locator('main').innerText()).length;
  await box.fill('In one sentence, what can you help me with?');
  await page.keyboard.press('Enter');
  await page.locator('[aria-label="Answering"]').first().waitFor({ timeout: 20_000 }).catch(() => {});
  await page.locator('[aria-label="Answering"]').first().waitFor({ state: 'detached', timeout: 120_000 }).catch(() => {});
  const failedMark = (await page.locator('[data-testid="send-failed"]').count()) + (await page.getByText(/answer stopped part-way|model call was refused/i).count());
  const after = (await page.locator('main').innerText()).length;
  report('chat turn answered', !failedMark && after > before + 40, failedMark ? 'send failed' : `answer ${after - before} chars`);
} else report('chat composer shown', false, 'no composer');

// Workflows: the first workflow opens, and a test run reaches an outcome.
await page.goto(`${origin}/workflows`, { waitUntil: 'domcontentloaded' });
await settle();
const first = page.locator('main table tbody tr a[href^="/workflows/"], main [role="row"] a[href^="/workflows/"]').first();
if (await first.waitFor({ timeout: 15_000 }).then(() => true, () => false)) {
  const name = (await first.innerText()).trim().slice(0, 60);
  await first.click();
  await page.locator('[data-testid="definition-canvas"]').first().waitFor({ timeout: 30_000 }).catch(() => {});
  report(`workflow opens: ${name}`, (await page.locator('[data-testid="definition-canvas"]').count()) > 0);
  const run = page.getByRole('button', { name: /^(start run|test run)$/i }).first();
  if (await run.count()) {
    await run.click();
    await settle();
    // A start form, if the workflow has inputs, is submitted as filled by its defaults.
    const start = page.getByRole('button', { name: /^(start|run|start run|run test)$/i }).first();
    if (await start.count()) await start.click().catch(() => {});
    const outcome = await page
      .locator('[aria-label="Done"], [aria-label="Failed"], [data-testid="ops-card-outcome"]')
      .first()
      .waitFor({ timeout: 120_000 })
      .then(() => true, () => false);
    const failedRun = await page.locator('[aria-label="Failed"]').count();
    report('workflow test run reaches an outcome', outcome, failedRun ? `${failedRun} step(s) failed` : '');
  } else report('workflow run button', false, 'no Start run button');
} else report('workflow list has a workflow', false, 'empty list');

// Settings: every page in the Settings tree opens without errors or not-found text.
await page.goto(`${origin}/settings`, { waitUntil: 'domcontentloaded' });
await settle();
const hrefs = await page
  .locator('a[href^="/settings/"]')
  .evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute('href')))]);
for (const href of hrefs) {
  await page.goto(`${origin}${href}`, { waitUntil: 'domcontentloaded' });
  await settle();
  const text = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
  const nf = /page not found|this page could not be found|something went wrong/i.test(text);
  report(`settings ${href}`, !nf, nf ? 'error text on page' : '');
}
if (!hrefs.length) report('settings pages listed', false, 'no settings links');

await browser.close();
console.log(failed ? `${failed} FAILED` : 'ALL OK');
process.exit(failed ? 1 : 0);
