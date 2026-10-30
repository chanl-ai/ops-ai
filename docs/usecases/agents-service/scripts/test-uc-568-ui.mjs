// uc-568 document workflows, ui layer: docs/usecases/agents-service/document-workflows.md (c-535). The demo stack with
// the embed app and the three console switches on, a workflow worker, and a fake model that also answers a propose read
// (the api script's rules, merged ahead of the demo's in a temporary folder). James Richardson, a team_ops builder,
// reads a 12-page scan as full text and as proposed fields, saves the proposal as a document type, picks what an
// Extract from file step reads, shares a workflow as a form that a person outside the console fills in the embed app,
// opens a members-only form in the console, and runs a workflow once per row of a CSV from the Start run dialog.
//
// The data-testid contract T002, T004 and T006 implement:
//   file-read-full-text   Read dialog (extract-dialog.tsx): the Full text choice
//   file-read-propose     Read dialog: "Let the model propose the fields"
//   file-text-tab         the file page's Text tab
//   file-text-page        one page of the Text tab, in page order; a word under 0.7 confidence inside it is a
//                         <mark data-confidence="0.xx">
//   proposed-field        a proposed field's editable name (an input whose value is the field's key)
//   save-document-type    the proposed read's Save as document type
//   step-what-to-read     the Extract from file step sheet's "What to read" select
//   share-as-form         Share as a form in the Request trigger's details
//   form-link             the shared form's link (an input's value, an anchor's href or its text)
//   form-qr               the shared form's QR code, an image of the link
//   form-rotate           Rotate, which asks first in an AlertDialog
//   hosted-form           the form a person fills: embed /f/<slug>?t=<token>, and the console's /forms/<slug>
//   hosted-form-send      its Send button
//   hosted-form-thanks    the thank-you after a submission
//   hosted-form-refused   why a submission or an opened link was refused (expired, rotated, the day's cap)
//   start-from-file       the Start run dialog's Start from a file tab
//   batch-dry-run         the dry run's result: the row count and the first 5 rows mapped to the inputs
//   batch-start           Start the runs
//   batch-headline        the batch page's "N of M finished, K failed"
//   batch-row             one row of the batch page's table, failed rows first
//   batch-retry-failed    Retry failed rows
//   batch-download        Download as CSV
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';

import { AGENTS_PORT, DOCUMENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

// The console's own pinned qrcode, to draw the QR code a shared link should show.
const QRCode = createRequire(new URL('../../../../apps/console/package.json', import.meta.url))('qrcode');

const SHOTS = evidenceDir('535', 'uc');
mkdirSync(SHOTS, { recursive: true });
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const documents = `http://127.0.0.1:${DOCUMENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PASSWORD = 'northfield-demo';
const RUN = Math.random().toString(36).slice(2, 8);
const READ_ID = `uc568ui_read_${RUN}`;
const FORM_ID = `uc568ui_form_${RUN}`;
const BATCH_ID = `uc568ui_batch_${RUN}`;
const API_SCRIPT = join(ROOT, 'docs/usecases/agents-service/scripts/test-uc-568-api.py');

// The api script owns the scan and the fake model's rules; this walk asks it for both, so the two layers read the
// same document the same way.
const fromApiScript = (expr) =>
  execFileSync('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', '-c', `
import importlib.util, sys
spec = importlib.util.spec_from_file_location("uc568", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
${expr}
`, API_SCRIPT], { env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') }, maxBuffer: 64 * 1024 * 1024 });
const SCAN = fromApiScript('sys.stdout.buffer.write(m.scan_pdf())');
const PROPOSE_RULES = JSON.parse(fromApiScript('import json; print(json.dumps(m.RULES))').toString()).rules;
const DEMO = JSON.parse(readFileSync(join(ROOT, 'services/models-service/seed/demo-fake-openai/script.json'), 'utf8'));
const RULES_DIR = mkdtempSync(join(tmpdir(), 'uc568-model-'));
writeFileSync(join(RULES_DIR, 'script.json'), JSON.stringify({ ...DEMO, rules: [...PROPOSE_RULES, ...(DEMO.rules ?? [])] }));

const FORM_SCHEMA = {
  type: 'object',
  title: 'Request a statement',
  required: ['customerId'],
  properties: { customerId: { type: 'string', title: 'Customer number' }, reason: { type: 'string', title: 'Why you need it' } },
};
const end = (id, outcome, failed = false) => ({ id, type: 'ops.flow.end', typeVersion: 1, name: outcome, parameters: { outcome, ...(failed ? { result: 'failed' } : {}) } });
const link = (from, port, to) => ({ from: { node: from, port }, to: { node: to, port: 'in' } });
const READ_FLOW = {
  schemaVersion: 2,
  id: READ_ID,
  name: 'Read a notice (uc-568)',
  nodes: [
    { id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request', parameters: { inputSchema: { type: 'object', required: ['fileId'], properties: { fileId: { type: 'string', format: 'file' } } } } },
    { id: 'read', type: 'ops.ai.extract', typeVersion: 1, name: 'Read the notice', parameters: { file: '$.input.fileId', read: 'text' } },
    ...['ok', 'review', 'unreadable', 'error'].map((p) => end(p, p)),
  ],
  connections: [link('start', 'payload', 'read'), ...['ok', 'review', 'unreadable', 'error'].map((p) => link('read', p, p))],
};
const FORM_FLOW = {
  schemaVersion: 2,
  id: FORM_ID,
  name: 'Statement request (uc-568)',
  nodes: [{ id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request', parameters: { inputSchema: FORM_SCHEMA } }, end('done', 'received')],
  connections: [link('start', 'payload', 'done')],
};
const BATCH_FLOW = {
  schemaVersion: 2,
  id: BATCH_ID,
  name: 'Customer check (uc-568)',
  nodes: [
    { id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request', parameters: { inputSchema: { type: 'object', required: ['customerId', 'status'], properties: { customerId: { type: 'string' }, status: { type: 'string' } } } } },
    { id: 'gate', type: 'ops.flow.if', typeVersion: 1, name: 'Marked bad?', parameters: { conditions: [{ left: '$.input.status', op: 'eq', right: 'bad' }] } },
    end('done', 'checked'),
    end('bad', 'rejected', true),
  ],
  connections: [link('start', 'payload', 'gate'), link('gate', 'false', 'done'), link('gate', 'true', 'bad')],
};
// 12 rows, rows 4 and 9 marked to fail.
const CSV = ['customerId,status,notes', ...Array.from({ length: 12 }, (_, i) => `CUS-${6001 + i},${[3, 8].includes(i) ? 'bad' : 'ok'},row ${i + 1}`)].join('\n');

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const body = async (r) => (await r.json().catch(() => ({}))) ?? {};
const said = async (r) => `${r.url.replace(/^https?:\/\/[^/]+/, '')} answered ${r.status}: ${(await r.clone().text()).slice(0, 200)}`;
const until = async (probe, ms = 90_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 500))) {
    const v = await probe();
    if (v) return v;
  }
  return null;
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const seen = (locator, timeout = 20_000) => locator.first().waitFor({ timeout }).then(() => true, () => false);

async function step(name, run) {
  try {
    await run();
  } catch (e) {
    // Playwright names the locator it waited for on a later line ("waiting for getByTestId(...)"): that is the red.
    const lines = String(e).split('\n');
    const waited = lines.find((l) => /waiting for/.test(l))?.trim() ?? '';
    check(name, false, `${lines[0]} ${waited}`.slice(0, 400));
  }
}

async function upload(J, name, bytes, mime) {
  const ticket = (await body(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: bytes.length, mime, purpose: 'case_attachment' }) }))).data;
  if (!ticket) throw new Error(`setup: upload ticket for ${name} refused`);
  const put = await fetch(new URL(ticket.uploadUrl, files).toString(), { method: 'PUT', headers: { ...J, ...ticket.headers }, body: bytes });
  if (put.status >= 300) throw new Error(`setup: upload of ${name} answered ${put.status}`);
  return (await body(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).data.file;
}

try {
  await withUiStack(
    async (consoleUrl, stack) => {
      await stack.startWorker();
      const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
      const H = { ...J, 'Content-Type': 'application/json' };
      for (const flow of [READ_FLOW, FORM_FLOW, BATCH_FLOW]) {
        const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: H, body: JSON.stringify({ definition: flow }) });
        // The read flow names `read`, which T001 adds; until then it is refused, and step 34 says so.
        if (saved.status !== 201 && flow !== READ_FLOW) throw new Error(`setup: ${flow.id} answered ${saved.status}: ${await saved.text()}`);
        if (flow !== READ_FLOW) await fetch(`${agents}/v1/workflows/definitions/${flow.id}/publish-requests`, { method: 'POST', headers: H, body: '{}' });
      }
      const scan = await upload(J, 'levy-scan.pdf', SCAN, 'application/pdf');
      const runsOf = async (wid) => ((await body(await fetch(`${agents}/v1/runs?workflowId=${wid}&pageSize=100`, { headers: J }))).data?.data ?? []);
      const narrow = {};
      const errors = [];
      const browser = await chromium.launch();
      try {
        const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true })).newPage();
        page.setDefaultTimeout(20_000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(JAMES);
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        const openRead = async () => {
          await page.goto(`${consoleUrl}/files/${scan.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('file-extract').click({ timeout: 60_000 });
        };

        // 31. The Read dialog offers Full text and "Let the model propose the fields".
        await step('31 the Read dialog offers Full text and Let the model propose the fields', async () => {
          await openRead();
          const full = await seen(page.getByTestId('file-read-full-text'));
          const propose = await seen(page.getByTestId('file-read-propose'), 2_000);
          const words = full && propose ? `${await page.getByTestId('file-read-full-text').innerText()} | ${await page.getByTestId('file-read-propose').innerText()}` : '';
          await page.screenshot({ path: join(SHOTS, 'read-dialog-1280.png') });
          check('31 the Read dialog offers Full text and Let the model propose the fields', full && propose && /Full text/i.test(words) && /propose the fields/i.test(words), { full, propose, words });
        });

        // 32. Full text, then the Text tab: 12 pages in order, low-confidence words shaded.
        await step('32 the Text tab shows the 12 pages in order with words under 0.7 confidence shaded', async () => {
          await openRead();
          await page.getByTestId('file-read-full-text').click();
          await page.getByTestId('extract-submit').click();
          await page.getByTestId('file-text-tab').click({ timeout: 240_000 });
          const pages = page.getByTestId('file-text-page');
          await pages.first().waitFor({ timeout: 120_000 });
          const texts = await pages.allInnerTexts();
          const order = texts.map((t) => (/Page (\d+) of 12/.exec(t) ?? [])[1]).map(Number);
          const marks = await page.locator('[data-testid="file-text-page"] mark[data-confidence]').evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-confidence'))));
          await page.screenshot({ path: join(SHOTS, 'text-tab-1280.png'), fullPage: true });
          await page.setViewportSize({ width: 375, height: 800 });
          await page.waitForTimeout(500);
          narrow.text = await sideways(page);
          await page.screenshot({ path: join(SHOTS, 'text-tab-375.png'), fullPage: true });
          await page.setViewportSize({ width: 1280, height: 900 });
          check('32 the Text tab shows the 12 pages in order with words under 0.7 confidence shaded', texts.length === 12 && order.join() === Array.from({ length: 12 }, (_, i) => i + 1).join() && marks.length > 0 && marks.every((c) => c < 0.7), { pages: texts.length, order, marks });
        });

        // 33. Propose, rename a field, Save as document type.
        await step('33 a proposed read with a renamed field saves as the team\'s document type', async () => {
          await openRead();
          await page.getByTestId('file-read-propose').click();
          await page.getByTestId('extract-submit').click();
          const names = page.getByTestId('proposed-field');
          await names.first().waitFor({ timeout: 240_000 });
          const keys = await names.evaluateAll((els) => els.map((e) => e.value ?? e.textContent));
          await names.nth(keys.indexOf('taxpayer')).fill('debtor_name');
          await page.screenshot({ path: join(SHOTS, 'proposed-read-1280.png'), fullPage: true });
          await page.getByTestId('save-document-type').click();
          const saved = await until(async () => {
            const items = (await body(await fetch(`${documents}/v1/document-types`, { headers: J }))).data?.items ?? [];
            for (const t of items) {
              const detail = (await body(await fetch(`${documents}/v1/document-types/${t.id}`, { headers: J }))).data;
              // The demo team already has a type with a debtor_name field: the saved one is the type whose first
              // sample is this scan.
              if (detail?.samples?.[0]?.fileId === scan.id && JSON.stringify(detail?.versions ?? []).includes('"debtor_name"')) return detail;
            }
            return null;
          }, 30_000);
          check('33 a proposed read with a renamed field saves as the team\'s document type, the file its first sample', keys.includes('taxpayer') && saved?.team === 'team_ops' && saved?.samples?.[0]?.fileId === scan.id, { keys, saved: saved ? { id: saved.id, team: saved.team, samples: saved.samples?.length } : null });
        });

        // 34. The Extract from file step's "What to read".
        await step('34 the Extract from file step offers what to read', async () => {
          const saved = await fetch(`${agents}/v1/workflows/definitions/${READ_ID}`, { headers: J });
          if (saved.status !== 200) throw new Error(`the workflow with an Extract step reading Full text was not saved: ${await said(saved)}`);
          await page.goto(`${consoleUrl}/workflows/definitions/${READ_ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.locator('[data-testid="definition-node"][data-node-id="read"]').click({ timeout: 60_000 });
          await page.getByTestId('step-what-to-read').click();
          const options = await page.getByRole('option').allInnerTexts();
          await page.keyboard.press('Escape');
          check('34 the Extract from file step offers what to read: Fields, Full text, Let the model propose the fields', ['Fields', 'Full text', 'Let the model propose the fields'].every((o) => options.some((t) => t.includes(o))), { options });
        });

        // 35. Share as a form on the Request trigger.
        let shared = '';
        await step('35 Share as a form gives a link and Rotate', async () => {
          await page.goto(`${consoleUrl}/workflows/definitions/${FORM_ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.locator('[data-testid="definition-node"][data-node-id="start"]').click({ timeout: 60_000 });
          await page.getByTestId('share-as-form').click();
          const create = page.getByRole('button', { name: /^(Share|Create link|Create)$/ });
          if (await seen(create, 3_000)) await create.first().click();
          const shownLink = page.getByTestId('form-link');
          await shownLink.first().waitFor();
          shared = (await shownLink.first().evaluate((e) => e.value || e.getAttribute('href') || e.textContent || '')).trim();
          const rotate = await seen(page.getByTestId('form-rotate'), 2_000);
          // The QR code is the link itself: the console's pinned qrcode package, with the console's options, draws the
          // same pixels from the link shown (the browser and Node encode the PNG differently, so bytes are not compared).
          const qr = page.getByTestId('form-qr');
          const qrShown = await seen(qr, 10_000);
          const qrSrc = qrShown ? await qr.first().getAttribute('src') : null;
          const qrWant = await QRCode.toDataURL(shared, { margin: 1, width: 224, errorCorrectionLevel: 'M' });
          const qrDownload = await seen(page.getByRole('link', { name: 'Download QR code' }), 2_000);
          const qrSame = qrSrc
            ? await page.evaluate(async ([a, b]) => {
                const pixels = async (src) => {
                  const img = new Image();
                  img.src = src;
                  await img.decode();
                  const c = document.createElement('canvas');
                  c.width = img.naturalWidth;
                  c.height = img.naturalHeight;
                  const g = c.getContext('2d');
                  g.drawImage(img, 0, 0);
                  return { w: c.width, data: Array.from(g.getImageData(0, 0, c.width, c.height).data) };
                };
                const [x, y] = [await pixels(a), await pixels(b)];
                return x.w === y.w && x.data.length === y.data.length && x.data.every((v, i) => v === y.data[i]);
              }, [qrSrc, qrWant])
            : false;
          await page.screenshot({ path: join(SHOTS, 'share-as-form-1280.png') });
          check(
            '35 Share as a form on the Request trigger gives a signed link to the embed app, its QR code and Rotate',
            /\/f\/[^/?]+\?t=fk\./.test(shared) && rotate && qrSame && qrDownload,
            { shared, rotate, qr: qrSrc ? qrSrc.slice(0, 40) : qrSrc, qrMatches: qrSame, qrDownload },
          );
        });

        // 36. The person with the link sees only the form, sends it, and gets the thank-you; a run starts.
        const outside = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
        outside.setDefaultTimeout(20_000);
        outside.on('pageerror', (e) => errors.push(e.message));
        await step('36 a person with the link fills the form and gets the thank-you, and a run starts', async () => {
          let url = shared;
          if (!url) {
            const made = await fetch(`${agents}/v1/workflows/${FORM_ID}/forms`, { method: 'POST', headers: H, body: JSON.stringify({ mode: 'link', expiresInDays: 30, dailyCap: 50, title: 'Request a statement' }) });
            if (made.status !== 201) throw new Error(`no link from the page, and the forms route refused: ${await said(made)}`);
            url = (await body(made)).data.url;
          }
          const target = new URL(url, stack.embedUrl);
          await outside.goto(`${stack.embedUrl}${target.pathname}${target.search}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const form = outside.getByTestId('hosted-form');
          await form.waitFor({ timeout: 60_000 });
          const shown = await form.innerText();
          await outside.getByLabel('Customer number').fill('CUS-1001');
          await outside.screenshot({ path: join(SHOTS, 'hosted-form-1280.png'), fullPage: true });
          await outside.setViewportSize({ width: 375, height: 800 });
          await outside.waitForTimeout(400);
          narrow.form = await sideways(outside);
          const send = await outside.getByTestId('hosted-form-send').boundingBox();
          narrow.formSend = !!send && send.x >= 0 && send.x + send.width <= 375;
          await outside.screenshot({ path: join(SHOTS, 'hosted-form-375.png'), fullPage: true });
          await outside.setViewportSize({ width: 1280, height: 900 });
          await outside.getByTestId('hosted-form-send').click();
          const thanks = await seen(outside.getByTestId('hosted-form-thanks'), 30_000);
          const run = await until(async () => (await runsOf(FORM_ID)).find((r) => String(r.createdBy).startsWith('trigger:form:')), 30_000);
          check('36 a person with the link sees only the form\'s title, description and fields, sends it, gets the thank-you, and a run starts', /Request a statement/.test(shown) && !shown.includes(FORM_ID) && !/received|ops\.flow/i.test(shown) && thanks && !!run, { shown: shown.slice(0, 200), thanks, run: run?.id });
        });

        // 37. A rotated link and a capped form say why they refuse.
        await step('37 a rotated link and a capped form are refused with why', async () => {
          let expired = '';
          if (shared && (await seen(page.getByTestId('form-rotate'), 2_000))) {
            await page.getByTestId('form-rotate').click();
            await page.getByRole('alertdialog').getByRole('button', { name: /Rotate/ }).click();
            await page.waitForTimeout(1_000);
            const old = new URL(shared, stack.embedUrl);
            await outside.goto(`${stack.embedUrl}${old.pathname}${old.search}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            expired = await outside.getByTestId('hosted-form-refused').innerText({ timeout: 30_000 }).catch(() => '');
          }
          const made = await fetch(`${agents}/v1/workflows/${FORM_ID}/forms`, { method: 'POST', headers: H, body: JSON.stringify({ mode: 'link', expiresInDays: 1, dailyCap: 1, title: 'Capped form' }) });
          if (made.status !== 201) throw new Error(`rotated link refusal "${expired}"; the capped form could not be made: ${await said(made)}`);
          const capped = (await body(made)).data;
          await fetch(`${agents}/v1/forms/public/${capped.slug}/submit?t=${encodeURIComponent(capped.token)}`, { method: 'POST', body: JSON.stringify({ values: { customerId: 'CUS-1002' } }), headers: { 'Content-Type': 'application/json', 'X-Forwarded-For': '198.51.100.20' } });
          const target = new URL(capped.url, stack.embedUrl);
          await outside.goto(`${stack.embedUrl}${target.pathname}${target.search}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await outside.getByLabel('Customer number').fill('CUS-1003');
          await outside.getByTestId('hosted-form-send').click();
          const full = await outside.getByTestId('hosted-form-refused').innerText({ timeout: 30_000 }).catch(() => '');
          await outside.screenshot({ path: join(SHOTS, 'hosted-form-refused-1280.png'), fullPage: true });
          check('37 a rotated link and a form past its daily cap are each refused with why, and start nothing', /expired|no longer|rotated/i.test(expired) && /today|limit|cap/i.test(full), { expired, full });
        });

        // 38. A members-only form opens in the console for a signed-in member.
        await step('38 a members-only form opens in the console for a member', async () => {
          const made = await fetch(`${agents}/v1/workflows/${FORM_ID}/forms`, { method: 'POST', headers: H, body: JSON.stringify({ mode: 'members', title: 'Members statement request' }) });
          if (made.status !== 201) throw new Error(`the members-only form could not be made: ${await said(made)}`);
          const { slug } = (await body(made)).data;
          await page.goto(`${consoleUrl}/forms/${slug}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const shown = await seen(page.getByTestId('hosted-form'), 60_000);
          check('38 a members-only form opens in the console for a signed-in member of its team', shown, { slug, shown });
        });

        // 39. Start from a file: the dry run, then Start.
        let batchUrl = '';
        await step('39 Start from a file shows the dry run and starts the runs', async () => {
          await page.goto(`${consoleUrl}/workflows/definitions/${BATCH_ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('definition-start-run').click({ timeout: 60_000 });
          await page.getByTestId('start-from-file').click();
          await page.locator('input[type="file"]').first().setInputFiles({ name: 'customers.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) });
          const dry = page.getByTestId('batch-dry-run');
          await dry.waitFor({ timeout: 60_000 });
          const shown = await dry.innerText();
          // Once the file is chosen the drop zone gives way to the file's own row; removing the file brings it back.
          const zone = page.getByRole('button', { name: /^Drop a CSV or Excel file here or choose one/ });
          const collapsed = !(await zone.isVisible()) && (await page.getByTestId('batch-file-items').innerText()).includes('customers.csv');
          await page.screenshot({ path: join(SHOTS, 'start-from-file-1280.png') });
          await page.getByTestId('batch-start').click();
          await page.waitForURL(/\/workflows\/batches\/[^/?]+/, { timeout: 60_000 });
          batchUrl = page.url();
          check('39 Start from a file shows the chosen file in place of the drop zone, the row count and the first 5 rows mapped, then starts one run per row', /\b12\b/.test(shown) && ['CUS-6001', 'CUS-6005'].every((c) => shown.includes(c)) && !shown.includes('CUS-6006') && /notes/.test(shown) && collapsed, { shown: shown.slice(0, 300), collapsed, batchUrl });
        });

        // 40. The batch page: counts, failed rows first, Retry failed rows, Download as CSV.
        await step('40 the batch page shows progress, retries failed rows and downloads the table', async () => {
          if (!batchUrl) throw new Error('no batch page: Start from a file did not start a batch');
          const headline = async () => {
            await page.reload({ waitUntil: 'domcontentloaded' });
            return (await page.getByTestId('batch-headline').innerText({ timeout: 30_000 }).catch(() => '')).trim();
          };
          const settled = await until(async () => {
            const h = await headline();
            return /10 of 12 finished, 2 failed/.test(h) ? h : null;
          }, 180_000);
          const rows = await page.getByTestId('batch-row').allInnerTexts();
          // The bar shows the failed share in the error colour beside the finished share: 2 of 12 failed, 10 finished.
          const share = async (id) => {
            const el = page.getByTestId(id);
            return (await el.count()) ? Number(await el.getAttribute('data-share')) : null;
          };
          const bar = { finished: await share('batch-bar-finished'), failed: await share('batch-bar-failed') };
          const failedColour = (await page.getByTestId('batch-bar-failed').getAttribute('class').catch(() => '')) ?? '';
          const barOk = bar.finished === 10 && bar.failed === 2 && /bg-destructive/.test(failedColour);
          await page.screenshot({ path: join(SHOTS, 'batch-1280.png'), fullPage: true });
          await page.setViewportSize({ width: 375, height: 800 });
          await page.waitForTimeout(500);
          narrow.batch = await sideways(page);
          await page.screenshot({ path: join(SHOTS, 'batch-375.png'), fullPage: true });
          await page.setViewportSize({ width: 1280, height: 900 });
          await page.getByTestId('batch-retry-failed').click();
          const confirm = page.getByRole('alertdialog').getByRole('button', { name: /Retry/ });
          if (await seen(confirm, 2_000)) await confirm.click();
          const retried = await until(async () => ((await runsOf(BATCH_ID)).length === 14 ? 14 : null), 90_000);
          const download = page.waitForEvent('download', { timeout: 30_000 });
          await page.getByTestId('batch-download').click();
          const saved = await (await download).path();
          const lines = readFileSync(saved, 'utf8').trim().split('\n');
          check('40 the batch page reads 10 of 12 finished, 2 failed, its bar shows the failed share in red, lists failed rows first, Retry failed rows starts only those 2, and Download as CSV gives the table', !!settled && rows.length === 12 && rows.slice(0, 2).every((r) => /failed/i.test(r)) && retried === 14 && lines.length === 13 && barOk, { settled, bar, failedColour, rows: rows.slice(0, 3), runs: (await runsOf(BATCH_ID)).length, lines: lines.length });
        });

        // 41. At 375 px the Text tab, the hosted form and the batch page fit.
        check('41 at 375 px the Text tab, the hosted form and the batch page do not scroll sideways and Send is on screen', narrow.text <= 0 && narrow.form <= 0 && narrow.formSend === true && narrow.batch <= 0, narrow);
        check('no page errors', errors.length === 0, errors);
      } finally {
        await browser.close();
      }
    },
    {
      demo: true,
      embed: true,
      fakeModelRules: relative(ROOT, RULES_DIR),
      consoleSwitches: { NEXT_PUBLIC_OPS_DOCUMENT_READS: '1', NEXT_PUBLIC_OPS_HOSTED_FORMS: '1', NEXT_PUBLIC_OPS_WORKFLOW_BUILDER: '1' },
    },
  );
} finally {
  rmSync(RULES_DIR, { recursive: true, force: true });
}

finish();
