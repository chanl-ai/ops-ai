// uc-125 a page on sample data says so and cannot be saved, a live setting persists, ui layer:
// docs/usecases/console/sample-data-pages-say-so.md. Signed in through platform-service as Sam (Security admin).
import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const SAM = 's.adeyemi@northfieldbank.com';
// Pages whose data is the mock's. Each must carry the notice and have no enabled control inside its gate.
const SAMPLE_PAGES = ['/account', '/account/security', '/settings/notifications', '/settings/sign-in', '/settings/webhooks', '/settings/api-keys', '/settings/policies/gates'];

const signIn = async (browser, consoleUrl, email) => {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => (page.errors ??= []).push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const sam = await signIn(browser, consoleUrl, SAM);
      const writes = [];
      sam.on('request', (r) => r.method() !== 'GET' && !/\/(telemetry|_next)\b/.test(r.url()) && writes.push(`${r.method()} ${new URL(r.url()).pathname}`));

      // Steps 1-2: every sample page says so, and nothing inside it can be pressed.
      const report = {};
      for (const path of SAMPLE_PAGES) {
        await sam.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const notice = sam.getByTestId('sample-data-notice');
        const shown = await notice.waitFor({ timeout: 120_000 }).then(() => true, () => false);
        await sam.getByTestId('sample-data-gate').first().waitFor({ state: 'attached', timeout: 30_000 }).catch(() => undefined);
        const text = shown ? await notice.innerText() : '';
        // The controls load after the notice; a sweep taken before they exist would pass with nothing to press.
        const controls = '[data-testid="sample-data-gate"] :is(button, input, select, textarea)';
        const loaded = await sam.waitForFunction((sel) => document.querySelectorAll(sel).length > 0, controls, { timeout: 60_000 }).then(() => true, () => false);
        const live = await sam.evaluate(
          (sel) => [...document.querySelectorAll(sel)].filter((e) => !e.matches(':disabled')).map((e) => e.getAttribute('aria-label') || e.textContent?.trim() || e.tagName),
          controls,
        );
        report[path] = { shown: shown && loaded && /Sample data, changes aren.t saved/.test(text), enabled: live.length === 0 ? 0 : live };
      }
      check('every sample-data page carries the notice and has no enabled control inside it', Object.values(report).every((r) => r.shown && r.enabled === 0), report);

      // Step 3: Gate policies carries a Preview badge in its header (the Reviews queue beside it is a real service).
      await sam.goto(`${consoleUrl}/settings/policies/gates`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const badge = await sam.getByTestId('page-header').getByTestId('preview-badge').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      await sam.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('page-header').waitFor({ timeout: 60_000 });
      await sam.waitForTimeout(500);
      const queueBadge = await sam.getByTestId('page-header').getByTestId('preview-badge').count();
      check('Gate policies shows Preview in its header and the real Reviews queue does not', badge && queueBadge === 0, { badge, queueBadge });

      // Step 4: try to edit a preview setting; nothing becomes editable, nothing is sent, and the value is the same after a reload.
      await sam.goto(`${consoleUrl}/settings/notifications`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = sam.getByRole('checkbox').first();
      await box.waitFor({ timeout: 120_000 });
      const before = await box.getAttribute('aria-checked');
      await box.click({ force: true, timeout: 5_000 }).catch(() => undefined);
      await sam.keyboard.press('Space');
      await sam.waitForTimeout(500);
      const bar = await sam.locator('[data-unsaved-bar]').count();
      const claimed = await sam.getByText(/Saved as version/).count();
      await sam.reload({ waitUntil: 'domcontentloaded' });
      await sam.getByRole('checkbox').first().waitFor({ timeout: 60_000 });
      const after = await sam.getByRole('checkbox').first().getAttribute('aria-checked');
      check('editing a preview setting opens no Save bar, claims no version, sends nothing and survives a reload unchanged', bar === 0 && claimed === 0 && before === after && writes.length === 0, { bar, claimed, before, after, writes });

      // Step 5: a webhook row opens no deliveries sheet (its Pause and Delete sit outside the gate).
      await sam.goto(`${consoleUrl}/settings/webhooks`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = sam.locator('tbody tr').first();
      await row.waitFor({ timeout: 120_000 });
      await row.click();
      await sam.waitForTimeout(500);
      check('a webhook row opens nothing on a sample page', (await sam.getByRole('dialog').count()) === 0 && writes.length === 0, writes);

      // Step 6: a live setting (Storage, files-service) saves a version and is still there after a reload, with no notice.
      await sam.goto(`${consoleUrl}/settings/storage`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const minutes = sam.getByLabel('Signed link lifetime');
      const was = await minutes.inputValue({ timeout: 120_000 });
      const next = was === '7' ? '8' : '7';
      await minutes.fill(next);
      await sam.getByTestId('storage-save').click();
      const saved = await sam.getByText(/Saved as version/).first().waitFor({ timeout: 15_000 }).then(() => true, () => false);
      await sam.reload({ waitUntil: 'domcontentloaded' });
      const kept = await sam.getByLabel('Signed link lifetime').inputValue({ timeout: 120_000 });
      const notice = await sam.getByTestId('sample-data-notice').count();
      check('a live setting saves a version, keeps its value after a reload and carries no sample notice', saved && kept === next && notice === 0, { was, next, kept, saved, notice });

      check('no page errors', (sam.errors ?? []).length === 0, sam.errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true } },
);

finish();
