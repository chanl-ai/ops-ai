// Uses a deployed console the way a person checks a release: a chat turn that gets an answer, a workflow run that
// reaches its end, and every Settings page. The click walk (stg_click_walk.mjs) proves pages open; this proves
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

// Workflows: a workflow opens, and a run started from its form reaches an end. The first workflow listed may need a file
// ("Extract a file"), so the walk starts the first whose form it can fill, and attaches a small sample file only when
// none can start without one. The end is read from the run page, by name: a run that ends Not saved is not a pass.
const SAMPLE = { name: 'staging-sample.txt', mimeType: 'text/plain', buffer: Buffer.from('A short sample for a staging test run.\n') };
const SETTLED = ['succeeded', 'failed', 'cancelled', 'waiting'];
let canvases = 0;

/** Opens `href`, presses Start run and submits its form; the run page's id, or why it could not start. */
async function startFrom(href, { withFile }) {
  await page.goto(`${origin}${href}`, { waitUntil: 'domcontentloaded' });
  if (await page.locator('[data-testid="definition-canvas"]').first().waitFor({ timeout: 30_000 }).then(() => true, () => false)) canvases++;
  const run = page.getByRole('button', { name: /^(start run|test run)$/i }).first();
  if (!(await run.count())) return { why: 'no Start run button' };
  await run.click();
  const dialog = page.getByRole('dialog').first();
  if (!(await dialog.waitFor({ timeout: 15_000 }).then(() => true, () => false))) return { why: 'no start form' };
  const files = dialog.locator('input[type="file"]');
  const needsFile = (await files.count()) > 0;
  if (needsFile && !withFile) {
    await page.keyboard.press('Escape');
    return { why: 'needs a file' };
  }
  for (let i = 0; i < (await files.count()); i++) await files.nth(i).setInputFiles(SAMPLE).catch(() => {});
  // Empty text fields get a sample value, as a person trying the workflow would type one.
  const fields = dialog.locator('input[type="text"]:visible, input:not([type]):visible, textarea:visible');
  for (let i = 0; i < (await fields.count()); i++) {
    const f = fields.nth(i);
    if (!(await f.inputValue().catch(() => 'x'))) await f.fill('Sample').catch(() => {});
  }
  const go = dialog.locator('[data-testid$="start-run-submit"]').first();
  await page.waitForTimeout(needsFile ? 3_000 : 500);
  if (await go.isDisabled().catch(() => true)) {
    await page.keyboard.press('Escape');
    return { why: 'its form needs input the walk cannot fill' };
  }
  await go.click();
  const at = await page.waitForURL(/\/workflows\/runs(\/[^/?]+$|\?run=)/, { timeout: 30_000 }).then(() => new URL(page.url()), () => null);
  const runId = at && (at.searchParams.get('run') ?? decodeURIComponent(at.pathname.split('/').pop() ?? ''));
  return runId ? { runId } : { why: 'no run page after Start' };
}

await page.goto(`${origin}/workflows`, { waitUntil: 'domcontentloaded' });
await settle();
const listed = await page
  .locator('main table tbody tr a[href^="/workflows/"], main [role="row"] a[href^="/workflows/"]')
  .evaluateAll((as) => [...new Map(as.map((a) => [a.getAttribute('href'), (a.innerText || '').split('\n')[0].trim().slice(0, 60)])).entries()].slice(0, 8));
if (listed.length) {
  let started = null;
  const tried = [];
  for (const withFile of [false, true]) {
    for (const [href, name] of listed) {
      if (started) break;
      const got = await startFrom(href, { withFile });
      if (got.runId) started = { ...got, name, withFile };
      else if (!withFile) tried.push(`${name}: ${got.why}`);
    }
  }
  report('workflow opens on its canvas', canvases > 0, started?.name ?? listed[0][1]);
  if (started) {
    await page.goto(`${origin}/workflows/runs/${encodeURIComponent(started.runId)}`, { waitUntil: 'domcontentloaded' });
    let status = '';
    for (const end = Date.now() + 120_000; Date.now() < end && !SETTLED.includes(status); await page.waitForTimeout(2_000)) {
      status = (await page.getByTestId('run-status').innerText({ timeout: 5_000 }).catch(() => '')).trim().toLowerCase();
    }
    const result = page.getByTestId('run-result');
    const outcome = (await result.count()) ? await result.getAttribute('data-outcome') : null;
    const ended = outcome ?? 'no end';
    const passed = status === 'succeeded' && !/not.?saved|fail|error|reject/i.test(ended);
    report(`workflow run reaches its end: ${started.name}${started.withFile ? ' (sample file)' : ''}`, passed, `${status || 'no status'}, ended ${ended}`);
  } else report('workflow run starts', false, tried.slice(0, 4).join('; '));
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
