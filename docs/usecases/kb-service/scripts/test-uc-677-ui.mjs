// uc-677 a knowledge owner turns on rerank and query rewrite, ui layer: docs/usecases/knowledge/rerank-and-rewrite.md, story S6. Signed in as James on the demo stack, whose kb-service calls models-service on the fake OpenAI
// answering from services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai; the owner turns Rerank on and asks the Playground.
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { KB_PORT, PLATFORM_PORT, check, chromium, finish, shootBothWidths, videoToGif, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const PAGES = [
  ['wire-cutoff', 'Wire cutoff', '## Cutoff\n\nA domestic wire sent after 5 pm goes out the next business day.'],
  ['wire-fees', 'Wire fees', '## Fees\n\nAn outgoing domestic wire costs 25 dollars.'],
];
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const post = async (path, body) => (await (await fetch(`${kb}${path}`, { method: 'POST', headers: H, body: JSON.stringify(body) })).json()).data;
      const base = await post('/v1/knowledge-bases', { name: `Payments ${TAG}`, owner: JAMES });
      const src = await post('/v1/sources', { type: 'text', name: `Payment pages ${TAG}`, kbIds: [base.id] });
      for (const [name, title, text] of PAGES) await post(`/v1/sources/${src.id}/items`, { name, title, text });

      const videos = mkdtempSync(join(tmpdir(), 'uc-677-video-'));
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
      await page.goto(`${consoleUrl}/data/knowledge/${base.id}?tab=settings`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('kb-settings-rerank').click({ timeout: 120_000 });
      await page.locator('#set-query-model').fill('default');
      const saving = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/knowledge-bases/${base.id}`), { timeout: 60_000 }));
      await page.getByTestId('kb-settings-save').click();
      const saved = await saving;
      const sent = saved ? JSON.parse(saved.request().postData() ?? '{}').retrieval : undefined;
      check('7 the Settings tab saves rerank on with the alias named', saved?.status() === 200 && sent?.rerank === true && sent?.queryModel === 'default', { status: saved?.status(), sent });

      await page.goto(`${consoleUrl}/data/knowledge/${base.id}?tab=playground`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.locator('#pg-question').fill('domestic wire', { timeout: 120_000 });
      await page.getByTestId('pg-ask').click();
      const rerank = page.getByTestId('search-rerank').first();
      await rerank.waitFor({ timeout: 60_000 });
      const said = await rerank.innerText();
      const header = await page.getByRole('columnheader', { name: 'Reranked' }).count();
      const firstRow = await page.getByTestId('search-trace').first().locator('tbody tr').first().innerText();
      check('8 the Playground says it reranked and shows the Reranked column, Wire fees first at 9 of 10', /Reranked 2 on default/.test(said) && header === 1 && /Wire fees/.test(firstRow) && /9 of 10/.test(firstRow), { said, header, firstRow });
      await page.waitForTimeout(1200);
      const clipMs = Date.now() - started;
      const state = await context.storageState();
      await context.close();
      videoToGif(videos, 'knowledge', 'uc-677-rerank', started - recording, clipMs);
      rmSync(videos, { recursive: true, force: true });

      // Stills of the same two screens at both widths, from a second context signed in the same way.
      const still = await browser.newContext({ viewport: { width: 1440, height: 1000 }, storageState: state });
      const shots = await still.newPage();
      await shootBothWidths(shots, 'knowledge', 'uc-677-retrieval-rerank', async () => {
        await shots.goto(`${consoleUrl}/data/knowledge/${base.id}?tab=settings`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await shots.getByTestId('kb-settings-rerank').waitFor({ timeout: 60_000 });
      });
      await shootBothWidths(shots, 'knowledge', 'uc-677-playground-reranked', async () => {
        await shots.goto(`${consoleUrl}/data/knowledge/${base.id}?tab=playground`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await shots.locator('#pg-question').fill('domestic wire', { timeout: 120_000 });
        await shots.getByTestId('pg-ask').click();
        await shots.getByTestId('search-rerank').first().waitFor({ timeout: 60_000 });
      });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, kbModels: true, fakeModelRules: 'services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai' },
);

finish();
