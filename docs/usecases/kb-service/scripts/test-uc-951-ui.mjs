// uc-951 open a deck or Word file as pages, ui layer: docs/usecases/kb-service/open-a-deck-or-word-file-as-pages.md, story S6 (steps 6-7).
// A pushed three-slide deck opens as its drawn slides beside its text; slide 2, only a picture, is described by a model, and choosing that description lights the whole slide. As an admin and as a viewer, at 1440 and 390.
// Needs the converter worker (make converter-up); documents-service is pointed at it through OPS_DOCUMENTS_CONVERTER_URL.
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { KB_PORT, MODELS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

process.env.OPS_DOCUMENTS_CONVERTER_URL ??= `http://127.0.0.1:${8780 + Number(process.env.OPS_PORT_OFFSET || 0)}`;
const worker = process.env.OPS_DOCUMENTS_CONVERTER_URL;
const up = await fetch(`${worker}/health`).then((r) => r.ok, () => false);
if (!up) {
  console.log(`FAIL the converter worker is not answering at ${worker}: run make converter-up first`);
  process.exit(1);
}

const kb = `http://127.0.0.1:${KB_PORT}`;
const BUILDER = 'j.richardson@harborpine.example';
const PEOPLE = { admin: 'p.shah@harborpine.example', viewer: 'r.menon@harborpine.example' };
const signedIn = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data;
const serviceToken = (tenant) =>
  execFileSync('uv', ['run', 'python', '-c', `from ops_identity import dev_service_signer, mint_service_token; print(mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="${tenant}", ttl_s=600))`], { cwd: join(ROOT, 'services/models-service'), encoding: 'utf8' }).trim();
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
      // The extract alias may see pictures, and the team sends page pictures to a model (a platform admin's switch).
      const platformAdmin = await signedIn('w.kamau@harborpine.example');
      const S = { Authorization: `Bearer ${serviceToken(platformAdmin.principal.tenantId)}`, 'Content-Type': 'application/json' };
      await fetch(`http://127.0.0.1:${MODELS_PORT}/v1/models/aliases`, { method: 'POST', headers: S, body: JSON.stringify({ name: 'extract', providerId: 'openai-local', modelId: 'default', images: true, clearedSensitivity: 'confidential' }) });
      const policy = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/policies/pageImages`, { method: 'PUT', headers: { Authorization: `Bearer ${platformAdmin.token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ value: true }) });
      check('the team sends page pictures to a model', policy.status === 200, await policy.text());
      const H = { Authorization: `Bearer ${await tokenFor(BUILDER)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const post = async (path, body) => (await (await fetch(`${kb}${path}`, { method: 'POST', headers: H, body: JSON.stringify(body) })).json()).data;
      const base = await post('/v1/knowledge-bases', { name: `Claims intake ${TAG}`, owner: BUILDER });
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
        await page.getByTestId('document-page-next').click();
        await page.getByText('Page 2 of 3').waitFor({ timeout: 60_000 });
        const described = page.getByTestId('document-text').locator('[data-block]').filter({ hasText: 'Mobile app sends work' });
        await described.first().waitFor({ timeout: 120_000 });
        const key = await described.first().getAttribute('data-block');
        await described.first().click();
        const lit = page.locator(`[data-box-key="${key}"][data-selected="true"]`);
        const box = await lit.first().evaluate((el) => ({ w: el.style.width, h: el.style.height })).catch(() => null);
        const byModel = await page.getByTestId('document-read-by').getByText('A model').count();
        check(`7 as ${role}, slide 2 is described by a model, and choosing the description lights the whole slide`, byModel === 1 && (await described.first().getAttribute('aria-pressed')) === 'true' && (await lit.count()) === 1 && box?.w === '100%' && box?.h === '100%', { key, box, byModel });
        await shootBothWidths(page, 'knowledge', `uc-951-deck-${role}`, async () => {
          await open();
          await page.getByTestId('document-page-next').click();
          await described.first().waitFor({ timeout: 60_000 });
          await described.first().click();
          await page.getByTestId('viewer-page-2').scrollIntoViewIfNeeded();
        });
        await context.close();
      }
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, fakeModelRules: 'services/kb-service/tests/fixtures/picture-reading-fake-openai' },
);

finish();
