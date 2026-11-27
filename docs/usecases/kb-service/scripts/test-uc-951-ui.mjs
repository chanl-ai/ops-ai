// uc-951 open a deck or Word file as pages, ui layer: docs/usecases/kb-service/open-a-deck-or-word-file-as-pages.md, story S6 (steps 6-7).
// A pushed three-slide deck opens as its drawn slides beside its text; choosing a paragraph lights its whole slide. As a builder and as a viewer, at 1440 and 390.
// Needs the converter worker (make converter-up); documents-service is pointed at it through OPS_DOCUMENTS_CONVERTER_URL.
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { KB_PORT, PLATFORM_PORT, check, chromium, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

process.env.OPS_DOCUMENTS_CONVERTER_URL ??= `http://127.0.0.1:${8780 + Number(process.env.OPS_PORT_OFFSET || 0)}`;
const worker = process.env.OPS_DOCUMENTS_CONVERTER_URL;
const up = await fetch(`${worker}/health`).then((r) => r.ok, () => false);
if (!up) {
  console.log(`FAIL the converter worker is not answering at ${worker}: run make converter-up first`);
  process.exit(1);
}

const kb = `http://127.0.0.1:${KB_PORT}`;
const PEOPLE = { builder: 'j.richardson@harborpine.example', viewer: 'r.menon@harborpine.example' };
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

// The api layer's deck (python-pptx), so every layer opens the same file.
const here = dirname(fileURLToPath(import.meta.url));
const deck = execFileSync('uv', ['run', '--quiet', 'python', '-c', `import base64, importlib.util, sys
s = importlib.util.spec_from_file_location("a", sys.argv[1]); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
print(base64.b64encode(m.deck()).decode())`, join(here, 'test-uc-951-api.py')], { cwd: join(here, '../../../../services/documents-service'), env: { ...process.env, PYTHONPATH: join(here, '../../lib') }, maxBuffer: 1 << 24 }).toString().trim();

async function signIn(page, consoleUrl, email) {
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const H = { Authorization: `Bearer ${await tokenFor(PEOPLE.builder)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const post = async (path, body) => (await (await fetch(`${kb}${path}`, { method: 'POST', headers: H, body: JSON.stringify(body) })).json()).data;
      const base = await post('/v1/knowledge-bases', { name: `Claims intake ${TAG}`, owner: PEOPLE.builder });
      const src = await post('/v1/sources', { type: 'push', name: `Project files ${TAG}`, kbIds: [base.id] });
      const mime = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
      const { item } = await post(`/v1/sources/${src.id}/items`, { name: 'project-update.pptx', content: deck, mime });

      for (const [role, email] of Object.entries(PEOPLE)) {
        const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(`${role}: ${e.message}`));
        await signIn(page, consoleUrl, email);
        const open = async () => {
          await page.goto(`${consoleUrl}/data/knowledge/documents/${item.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('document-text').locator('[data-block]').first().waitFor({ timeout: 180_000 });
          await page.getByTestId('viewer-page-1').locator('img').waitFor({ timeout: 120_000 });
        };
        await open();
        check(`6 as ${role}, the deck opens as its drawn slides`, (await page.getByText('Page 1 of 3').count()) === 1, { url: page.url() });
        const paragraph = page.getByTestId('document-text').locator('[data-block]').first();
        const key = await paragraph.getAttribute('data-block');
        await paragraph.click();
        const lit = page.locator(`[data-box-key="${key}"][data-selected="true"]`);
        const box = await lit.first().evaluate((el) => ({ w: el.style.width, h: el.style.height })).catch(() => null);
        check(`7 as ${role}, choosing a paragraph lights its whole slide`, (await paragraph.getAttribute('aria-pressed')) === 'true' && (await lit.count()) === 1 && box?.w === '100%' && box?.h === '100%', { key, box });
        await shootBothWidths(page, 'knowledge', `uc-951-deck-${role}`, async () => {
          await open();
          await paragraph.click();
          await page.getByTestId('viewer-page-1').scrollIntoViewIfNeeded();
        });
        await context.close();
      }
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
