// uc-331 A file is read with Detect from the Files page, ui layer: docs/usecases/files-service/a-file-is-read-with-detect.md
// (c-335). The demo stack with the documents fixtures' fake model, which knows the invoice fixtures and answers that a
// canteen menu is none of the team's types; platform sign-in as James. A workflow worker runs the system extract.
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = evidenceDir('335', 'screens');
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

// A one-page menu, text a PDF reader extracts: none of the team's document types.
function menuPdf() {
  const lines = ['Staff canteen menu for the week', 'Monday: lentil soup', 'Tuesday: fish pie'];
  const text = `BT /F1 16 Tf 72 720 Td ${lines.map((l, i) => `${i ? '0 -24 Td ' : ''}(${l}) Tj`).join(' ')} ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let out = '%PDF-1.7\n';
  const at = objects.map((body, i) => {
    const offset = out.length;
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
    return offset;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${at.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(out);
}

async function upload(J, name, body) {
  const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: body.length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
  const put = await fetch(new URL(ticket.uploadUrl, files).toString(), { method: 'PUT', headers: { ...J, ...ticket.headers }, body });
  if (put.status !== 204) throw new Error(`setup: upload of ${name} answered ${put.status}`);
  return (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).file;
}

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
    const invoice = await upload(J, 'INVA01.pdf', readFileSync(join(ROOT, 'services/documents-service/tests/fixtures/invoice/INVA01.pdf')));
    const menu = await upload(J, 'canteen-menu.pdf', menuPdf());
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      const extract = async (file) => {
        await page.goto(`${consoleUrl}/files/${file.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('file-extract').click();
        await page.getByTestId('extract-type').click();
        const first = (await page.getByRole('option').first().innerText()).trim();
        const enabled = (await page.getByRole('option').first().getAttribute('aria-disabled')) !== 'true';
        await page.getByTestId('extract-detect').click();
        const versionShown = await page.getByTestId('extract-version').count();
        if (file === invoice) {
          // c-335's screen evidence: the dialog with Detect chosen, at 1280 and 400.
          mkdirSync(SHOTS, { recursive: true });
          await page.getByRole('listbox').waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => undefined);
          await page.waitForTimeout(500);
          await page.screenshot({ path: join(SHOTS, 'extract-detect-1280.png') });
          await page.setViewportSize({ width: 400, height: 800 });
          await page.waitForTimeout(400);
          await page.screenshot({ path: join(SHOTS, 'extract-detect-400.png') });
          await page.setViewportSize({ width: 1280, height: 900 });
        }
        await page.getByTestId('extract-submit').click();
        await page.getByText(`Read ${file.name}`).first().waitFor({ timeout: 240_000 });
        return { first, enabled, versionShown };
      };
      // A read that waits on a person is approved by Maya, a Reviewer of Operations; its run is the one the page opened.
      const approveIfWaiting = async () => {
        await page.waitForURL((u) => u.searchParams.has('run'), { timeout: 30_000 }).catch(() => undefined);
        const runId = new URL(page.url()).searchParams.get('run');
        const M = { Authorization: `Bearer ${await tokenFor(MAYA)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
        for (let i = 0; i < 60; i++) {
          const run = runId ? await data(await fetch(`${agents}/v1/runs/${runId}`, { headers: J })).catch(() => null) : null;
          if (run && ['succeeded', 'failed', 'cancelled'].includes(run.status)) return { runId, status: run.status };
          if (run?.status === 'waiting' && run.waiting) {
            const r = await fetch(`${agents}/reviews/${encodeURIComponent(`${runId}:${run.waiting.node}:${run.waiting.iteration}`)}/decision`, { method: 'POST', headers: M, body: JSON.stringify({ decision: 'approved' }) });
            return { runId, status: 'approved', decided: r.status };
          }
          await new Promise((r) => setTimeout(r, 1000));
        }
        return { runId, status: 'timeout' };
      };
      const readAsOf = async (file, want) => {
        let said = '';
        for (let i = 0; i < 30 && !want.test(said); i++) {
          await page.goto(`${consoleUrl}/files/${file.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          said = (await page.getByTestId('read-as').first().innerText({ timeout: 5_000 }).catch(() => '')).replace(/\s+/g, ' ');
          if (!want.test(said)) await page.waitForTimeout(2000);
        }
        return said;
      };

      await step('1 Detect is the first choice; it hides the version and reads the invoice as the type it finds', async () => {
        await page.goto(`${consoleUrl}/files/${invoice.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('file-extract').click();
        const placeholder = (await page.getByTestId('extract-type').innerText()).trim();
        await page.keyboard.press('Escape');
        const seen = await extract(invoice);
        const run = await approveIfWaiting();
        const readAs = await readAsOf(invoice, /Supplier invoice/);
        check(
          '1 Detect is the first choice; it hides the version and reads the invoice as the type it finds',
          seen.first === 'Detect the type' && seen.enabled && /Choose a type/.test(placeholder) && seen.versionShown === 0 && /Supplier invoice/.test(readAs),
          { ...seen, placeholder, readAs, run },
        );
      });

      await step('2 a file of no known type, once its check is approved, reads as Not recognised, and its preview survives a resize', async () => {
        await extract(menu);
        // The read waits on a person for the type it could not find.
        const run = await approveIfWaiting();
        const readAs = await readAsOf(menu, /Not recognised/);
        await page.getByTestId('viewer-page-1').waitFor({ timeout: 30_000 }).catch(() => undefined);
        // It says how to read it after all, and its fields pane says none were read with the same way out.
        const hint = (await page.getByTestId('read-as').first().innerText()).includes('Extract again and choose its type');
        const empty = (await page.getByTestId('file-no-fields').count()) > 0;
        await page.screenshot({ path: join(SHOTS, 'read-as-not-recognised-1280.png') });
        await page.setViewportSize({ width: 400, height: 800 });
        // Across the phone breakpoint the viewer mounts again and must still draw the file.
        const redrawn = await page.getByTestId('viewer-page-1').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        await page.waitForTimeout(400);
        await page.screenshot({ path: join(SHOTS, 'read-as-not-recognised-400.png') });
        await page.setViewportSize({ width: 1280, height: 900 });
        check('2 a file of no known type, once its check is approved, reads as Not recognised, and its preview survives a resize', run.decided === 200 && /Not recognised/.test(readAs) && redrawn && hint && empty, { run, readAs, redrawn, hint, empty });
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true, fakeModelRules: 'services/documents-service/tests/fixtures/fake-model' },
);
finish();
