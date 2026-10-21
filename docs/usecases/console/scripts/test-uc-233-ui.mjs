// uc-233 A workflow runs from a form, with files attached, ui layer: docs/usecases/console/run-with-files.md (c-273).
// Platform sign-in; James works in Operations, where the seed holds levy_files (a Request trigger taking files).
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const SHOTS = process.env.UC233_SHOTS ?? join(ROOT, 'docs/console/proposed/run-with-files');
const PDF = join(ROOT, 'services/documents-service/tests/fixtures/restraining/TEST012.pdf');
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    // A Request trigger taking files and one field of each kind the form draws.
    const WID = 'uc233_files_intake';
    const inputSchema = {
      type: 'object',
      properties: {
        files: { type: 'array', items: { type: 'object', properties: { fileId: { type: 'string' }, name: { type: 'string' } }, required: ['fileId'] } },
        note: { type: 'string', description: 'What the files are about' },
        amount: { type: 'number', format: 'money' },
        due: { type: 'string', format: 'date' },
        urgent: { type: 'boolean' },
        kind: { type: 'string', enum: ['levy', 'warrant'] },
      },
      required: ['files'],
    };
    const definition = {
      schemaVersion: 2,
      id: WID,
      name: 'Files intake (uc-233)',
      nodes: [
        { id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Files to read', parameters: { inputSchema }, position: { x: 0, y: 0 } },
        { id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: { outcome: 'received' }, position: { x: 400, y: 0 } },
      ],
      connections: [{ from: { node: 'start', port: 'payload' }, to: { node: 'done', port: 'in' } }],
    };
    const saved = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition }) })).json();
    if (!saved.data) throw new Error(`setup: ${JSON.stringify(saved).slice(0, 300)}`);
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      const dialog = page.getByRole('dialog', { name: /Start a run of/ });
      await step('1 Test run shows a Files field with upload and picker, a control per input kind, and a JSON tab', async () => {
        await page.goto(`${consoleUrl}/workflows/definitions/${WID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('definition-start-run').click({ timeout: 120_000 });
        await dialog.waitFor();
        const files = dialog.getByTestId('run-files-files');
        await files.waitFor();
        const upload = await dialog.getByTestId('run-files-files-upload').count();
        const pick = await dialog.getByTestId('run-files-files-pick').count();
        const json = await dialog.getByTestId('run-input-json-tab').count();
        // One control per kind: a date input, a number, a switch and a choice.
        const kinds = {
          date: await dialog.locator('input[type="date"]').count(),
          number: await dialog.locator('input[type="number"]').count(),
          yesNo: await dialog.getByRole('switch').count(),
          choice: await dialog.getByRole('combobox').count(),
        };
        // A field without a schema title is named in words, never by its camelCase key.
        const labels = (await dialog.locator('label').allInnerTexts()).map((t) => t.trim()).filter(Boolean);
        // c-273's screen evidence: the run form with its Files field at 1280 and 400.
        mkdirSync(join(ROOT, '.codeloop/evidence/273/screens'), { recursive: true });
        // At the review widths once the dialog has settled, then the same input as JSON.
        for (const width of [1280, 400]) {
          await page.setViewportSize({ width, height: 800 });
          await page.waitForTimeout(600);
          await page.screenshot({ path: join(ROOT, `.codeloop/evidence/273/screens/run-form-${width}.png`) });
        }
        await page.setViewportSize({ width: 1280, height: 800 });
        await dialog.getByTestId('run-input-json-tab').click();
        await page.waitForTimeout(400);
        await page.screenshot({ path: join(ROOT, '.codeloop/evidence/273/screens/run-form-json-1280.png') });
        await dialog.getByTestId('run-input-form-tab').click();
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('1b every input is labelled in words, with no camelCase key', labels.length > 0 && labels.every((t) => !/[a-z][A-Z]/.test(t)), { labels });
        check('1 Test run shows a Files field with upload and picker, a control per input kind, and a JSON tab', upload === 1 && pick === 1 && json === 1 && kinds.date === 1 && kinds.number === 1 && kinds.yesNo === 1 && kinds.choice >= 1, { upload, pick, json, kinds });
      });

      await step('2 an uploaded file reaches the run as its id and name', async () => {
        await dialog.locator('input[type="file"]').first().setInputFiles(PDF);
        await dialog.getByText('TEST012.pdf').first().waitFor({ timeout: 60_000 });
        // The JSON tab shows the same input once the upload has its id.
        let input = {};
        for (let i = 0; i < 60; i++) {
          await dialog.getByTestId('run-input-json-tab').click();
          input = JSON.parse((await dialog.getByTestId('definition-run-input').inputValue()) || '{}');
          if (input.files?.[0]?.fileId) break;
          await dialog.getByTestId('run-input-form-tab').click();
          await page.waitForTimeout(500);
        }
        await dialog.getByTestId('run-input-form-tab').click();
        mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({ path: join(SHOTS, 'run-with-files-1440.png') });
        await dialog.getByRole('radio', { name: /Test run/ }).click();
        const started = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/runs$/.test(r.url()), { timeout: 60_000 });
        await dialog.getByTestId('definition-start-run-submit').click();
        const res = await started;
        const body = JSON.parse(res.request().postData() ?? '{}');
        const runId = (await res.json()).data?.runId;
        const run = runId ? (await (await fetch(`${agents}/v1/runs/${runId}`, { headers: J })).json()).data : null;
        check(
          '2 an uploaded file reaches the run as its id and name',
          res.status() < 300 && body.mode === 'test' && input.files?.[0]?.name === 'TEST012.pdf' && /^fil_/.test(input.files?.[0]?.fileId ?? '') && run?.input?.files?.[0]?.fileId === input.files[0].fileId,
          { status: res.status(), mode: body.mode, input, runInput: run?.input },
        );
        // The run page links the file by the name it was uploaded with, from the run the server returns.
        await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const link = page.getByTestId('run-files').getByRole('link', { name: 'TEST012.pdf' });
        const linked = await link.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const href = linked ? await link.getAttribute('href') : null;
        check('2b the run page links the file by its name', linked && href === `/files?file=${input.files?.[0]?.fileId}`, { linked, href });
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
