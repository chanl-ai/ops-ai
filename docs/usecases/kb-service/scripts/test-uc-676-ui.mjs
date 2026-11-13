// uc-676 typed text and pushed items become cited knowledge, ui layer: docs/usecases/kb-service/typed-text-and-pushed-
// items.md, story S6. Signed in through platform-service as James, a builder adds a typed text source in Add source and
// the agents' search returns the page.
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { KB_PORT, PLATFORM_PORT, check, chromium, finish, shootBothWidths, videoToGif, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const videos = mkdtempSync(join(tmpdir(), 'uc-676-video-'));
      const recording = Date.now();
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: videos, size: { width: 1440, height: 900 } } });
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      const started = Date.now();
      await page.goto(`${consoleUrl}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'New knowledge base' }).first().click({ timeout: 120_000 });
      await page.getByLabel('Name').fill(`Teller notes ${TAG}`);
      const made = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/knowledge-bases'), { timeout: 60_000 }));
      await page.getByTestId('kb-create').click();
      const kbId = (await (await made).json()).data.id;
      await page.waitForURL(`**/knowledge/${kbId}**`, { timeout: 60_000 });

      await page.getByTestId('kb-add-source').click({ timeout: 60_000 });
      await page.getByTestId('kb-add-apps').click();
      const add = page.getByTestId('add-source-wizard');
      await page.waitForTimeout(1000);
      await add.getByTestId('add-source-kind-text').click({ timeout: 60_000 });
      await page.waitForTimeout(800);
      await add.getByTestId('add-source-next').click();
      await add.getByTestId('add-source-name').fill(`Teller pages ${TAG}`);
      const fields = (await add.getByTestId('add-source-page-title').count()) + (await add.getByTestId('add-source-page-text').count());
      await add.getByTestId('add-source-page-title').fill('Night deposit');
      await add.getByTestId('add-source-page-text').fill('## Night deposit bags\n\nA night deposit bag is opened by two tellers before 9 am.');
      await page.waitForTimeout(1200);
      await add.getByTestId('add-source-next').click();
      await add.getByRole('heading', { name: 'Defaults applied' }).waitFor({ timeout: 30_000 });
      const noSchedule = (await add.getByRole('heading', { name: 'Schedule' }).count()) === 0;
      check('11 Typed text asks for a title and Markdown, and its review offers no schedule', fields === 2 && noSchedule, { fields, noSchedule });

      await page.waitForTimeout(1200);
      const creating = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/sources'), { timeout: 60_000 }));
      const writing = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/sources\/[^/]+\/items$/.test(r.url()), { timeout: 60_000 }));
      await add.getByTestId('add-source-create').click();
      const created = await creating;
      const written = await writing;
      const put = written ? (await written.json()).data : undefined;
      check('12 Create and sync makes the source, then writes the page into it, indexed', created?.status() === 201 && put?.outcome === 'created' && put?.item?.status === 'indexed', { created: created?.status(), put });

      const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const found = (await (await fetch(`${kb}/v1/knowledge-bases/search`, { method: 'POST', headers: H, body: JSON.stringify({ kbIds: [kbId], question: 'night deposit bag tellers' }) })).json()).data;
      check('13 the base’s search returns the typed page', found?.passages?.some((p) => p.text.includes('two tellers')), found?.passages?.slice(0, 1));
      const listed = await page.getByRole('row', { name: /Teller pages .*Typed text/ }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('the base’s Sources tab lists the typed source', listed);
      await page.waitForTimeout(1200);
      const clipMs = Date.now() - started;
      const state = await context.storageState();
      await context.close();
      videoToGif(videos, 'knowledge', 'uc-676-typed-text', started - recording, clipMs);
      rmSync(videos, { recursive: true, force: true });

      // Stills of the same screens at both widths, from a second context signed in the same way.
      const still = await browser.newContext({ viewport: { width: 1440, height: 1000 }, storageState: state });
      const shots = await still.newPage();
      const baseUrl = `${consoleUrl}/knowledge/${kbId}?tab=sources`;
      await shootBothWidths(shots, 'knowledge', 'uc-676-base-after-sync', async () => {
        await shots.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await shots.getByRole('row', { name: /Teller pages .*Typed text/ }).waitFor({ timeout: 60_000 });
      });
      await shootBothWidths(shots, 'knowledge', 'uc-676-add-typed-text', async () => {
        await shots.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await shots.getByTestId('kb-add-source').click({ timeout: 60_000 });
        await shots.getByTestId('kb-add-apps').click();
        const wizard = shots.getByTestId('add-source-wizard');
        await wizard.getByTestId('add-source-kind-text').click({ timeout: 60_000 });
        await wizard.getByTestId('add-source-next').click();
        await wizard.getByTestId('add-source-page-title').fill('Cash handling');
        await wizard.getByTestId('add-source-page-text').fill('## Cash handling\n\nCount every drawer twice.');
      });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
