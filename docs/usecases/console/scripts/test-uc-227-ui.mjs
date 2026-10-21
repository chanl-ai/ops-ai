// uc-227 A file is read on its own page, ui layer: docs/usecases/console/file-extraction.md (c-262). Platform sign-in;
// James works in Operations, where the stack's seed put the restraining-notice samples. Demo mode, so extractions run
// on models-service against the fake model, whose rule for TEST012 leaves the garnishee off the page.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, DOCUMENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const documents = `http://127.0.0.1:${DOCUMENTS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// Screenshots for the owner to approve; approved screens then move to docs/console/approved/files.
const SHOTS = process.env.UC227_SHOTS ?? join(ROOT, 'docs/console/proposed/files');

const runOf = {};

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    // Extract starts the system extract workflow, which a worker runs.
    await stack.startWorker();
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
    const listed = await json(await fetch(`${files}/v1/files?page=1&pageSize=20&search=TEST012`, { headers: J }));
    const file = listed.data.find((f) => f.name === 'TEST012.pdf');
    if (!file) throw new Error(`setup: TEST012.pdf is not in Operations: ${listed.data.map((f) => f.name).join(', ')}`);
    const fileUrl = `${consoleUrl}/files/${file.id}`;

    // A PDF draws inside a frame only in a full Chrome; Playwright's headless shell leaves the frame blank.
    const browser = await chromium.launch({ channel: process.env.UC227_CHANNEL ?? 'chrome' });
    const errors = [];
    try {
      const signIn = async (width) => {
        const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
        page.setDefaultTimeout(60_000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(JAMES);
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        return page;
      };
      const page = await signIn(1280);
      mkdirSync(SHOTS, { recursive: true });

      await step('1 the Files row reads Not read and its name opens the file page', async () => {
        await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByPlaceholder(/search/i).first().fill('TEST012');
        const link = page.getByTestId(`file-open-${file.id}`);
        await link.waitFor();
        const row = page.locator('tr', { has: link });
        const before = await row.getByText('Not read').count();
        await link.click();
        await page.waitForURL((u) => u.pathname === `/files/${file.id}`);
        const title = await page.getByTestId('page-title').first().innerText();
        check('1 the Files row reads Not read and its name opens the file page', before === 1 && title.includes('TEST012.pdf'), { before, title });
      });

      await step('2 Preview shows the PDF with Not read yet and Extract beside it', async () => {
        // pdf.js draws each page, so boxes can sit over it.
        const pageOne = page.getByTestId('document-viewer').getByTestId('viewer-page-1');
        await pageOne.locator('img').waitFor({ timeout: 60_000 });
        const src = await pageOne.locator('img').getAttribute('src');
        const empty = await page.getByText('Not read yet').count();
        await page.waitForTimeout(2500);
        await page.screenshot({ path: join(SHOTS, 'file-preview-unread-1280.png') });
        check('2 Preview shows the PDF with Not read yet and Extract beside it', /^data:image\/png/.test(src ?? '') && empty === 1 && (await page.getByTestId('file-extract').isVisible()), { src: src?.slice(0, 40), empty });
      });

      await step('3 Extract reads the file, lands on Fields and marks the field that is not on the page', async () => {
        await page.getByTestId('file-extract').click();
        const dialog = page.getByRole('dialog', { name: 'Extract' });
        await dialog.getByTestId('extract-type').click();
        await page.getByRole('option', { name: 'Restraining notice' }).click();
        await page.getByRole('listbox').waitFor({ state: 'detached' }).catch(() => null);
        await page.waitForTimeout(300);
        await page.screenshot({ path: join(SHOTS, 'extract-dialog-1280.png') });
        await dialog.getByTestId('extract-submit').click();
        // The toast sits at the top, off the fields it just filled.
        const toastAtTop = await page.locator('[data-sonner-toaster][data-y-position="top"]').getByText('Read TEST012.pdf').waitFor({ timeout: 180_000 }).then(() => true, () => false);
        const landed = await page.waitForURL((u) => u.pathname === `/files/${file.id}/fields`, { timeout: 180_000 }).then(() => true, () => false);
        if (!landed) throw new Error(`still on ${page.url()}; the dialog says: ${await page.getByTestId('extract-error').innerText().catch(() => '(no error shown)')}`);
        // Extract started the system extract workflow as James, and the page links its run.
        const runId = new URL(page.url()).searchParams.get('run');
        const linked = await page.getByTestId('file-last-run-link').getAttribute('href');
        const run = await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: J }));
        runOf.id = runId;
        runOf.run = run;
        const caseRow = page.getByTestId('read-field-0-case_no');
        await caseRow.waitFor({ timeout: 60_000 });
        const caseText = await caseRow.innerText();
        const garnishee = await page.getByTestId('read-field-0-garnishee').getAttribute('data-needs-review');
        const debtor = await page.getByTestId('read-field-0-debtor_name').getAttribute('data-needs-review');
        // An optional field the notice does not carry reads as absent, with no confidence to show.
        const agency = page.getByTestId('read-field-0-issuing_agency');
        const agencyText = await agency.innerText();
        const agencyBars = await agency.getByRole('progressbar').count() + (agencyText.includes('%') ? 1 : 0);
        const reads = await json(await fetch(`${documents}/v1/documents/extractions?fileId=${file.id}&page=1&pageSize=5`, { headers: J }));
        const newest = reads.data[0];
        await page.screenshot({ path: join(SHOTS, 'file-fields-1280.png'), fullPage: true });
        check(
          '3 Extract reads the file, lands on Fields and marks the field that is not on the page',
          newest?.status === 'done' && newest.documentType?.id === 'restraining_notice' && caseText.includes('SYN-2026-0012') && garnishee === 'true' && debtor === 'false' && (newest.needsReview ?? []).includes('garnishee') && agencyText.includes('Not on the page') && agencyBars === 0 && toastAtTop,
          { status: newest?.status, type: newest?.documentType, caseText: caseText.slice(0, 120), garnishee, debtor, needsReview: newest?.needsReview, agencyText, agencyBars, toastAtTop },
        );
        check(
          '3b Extract ran the system extract workflow as James, the page links that run, and it waits for the doubtful field to be checked',
          run?.workflowId === 'system_extract' && linked === `/workflows/runs/${runId}` && run?.status === 'waiting' && !!run?.waiting,
          { runId, linked, workflowId: run?.workflowId, status: run?.status },
        );
      });

      await step('4 the Files list says how the file was read, as files-service records it', async () => {
        // A person approves the check in Human Tasks; the workflow then saves what was read on the file.
        const w = runOf.run.waiting;
        // Maya approves for Operations; James builds and does not decide reviews.
        const M = { Authorization: `Bearer ${await tokenFor('m.okafor@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
        const decided = await fetch(`${agents}/reviews/${encodeURIComponent(`${runOf.id}:${w.node}:${w.iteration}`)}/decision`, { method: 'POST', headers: M, body: JSON.stringify({ decision: 'approve' }) });
        if (!decided.ok) throw new Error(`decision ${decided.status}: ${(await decided.text()).slice(0, 300)}`);
        let finished;
        for (let i = 0; i < 90; i++) {
          finished = await json(await fetch(`${agents}/v1/runs/${runOf.id}`, { headers: J }));
          if (['succeeded', 'failed', 'cancelled'].includes(finished.status)) break;
          await new Promise((r) => setTimeout(r, 1000));
        }
        if (finished?.outcome !== 'saved') throw new Error(`the run ended ${finished?.status} / ${finished?.outcome}`);
        const detail = await json(await fetch(`${files}/v1/files/${file.id}`, { headers: J }));
        await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByPlaceholder(/search/i).first().fill('TEST012');
        const row = page.locator('tr', { has: page.getByTestId(`file-open-${file.id}`) });
        await row.getByTestId('read-as').waitFor({ timeout: 60_000 });
        const said = await row.getByTestId('read-as').innerText();
        await page.screenshot({ path: join(SHOTS, 'files-read-as-1280.png') });
        check(
          '4 the Files list says how the file was read, as files-service records it',
          detail.data?.typeId === 'restraining_notice' && said.includes(`${detail.data.typeName ?? 'restraining_notice'} v${detail.data.version} · ${detail.data.path}`) && (detail.data.fieldsToCheck ? said.includes('to check') : !said.includes('to check')),
          { data: detail.data, said },
        );
      });

      await step('5 Activity lists the read and Versions lists version 1 as current', async () => {
        await page.goto(`${fileUrl}/activity`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const activity = await page.getByTestId('file-activity').innerText();
        await page.goto(`${fileUrl}/versions`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const versions = await page.getByTestId('file-versions').innerText();
        check('5 Activity lists the read and Versions lists version 1 as current', activity.includes('Read as Restraining notice v1') && activity.includes('1 field to check') && versions.includes('Version 1') && versions.includes('Current'), { activity: activity.slice(0, 200), versions: versions.slice(0, 120) });
      });

      await step('6 at 400 px the file page does not scroll sideways', async () => {
        const phone = await signIn(400);
        const widths = {};
        for (const path of ['', '/fields']) {
          await phone.goto(`${fileUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await phone.getByTestId('page-title').first().waitFor();
          await phone.waitForTimeout(2500);
          widths[path || '/'] = await phone.evaluate(() => document.documentElement.scrollWidth);
          await phone.screenshot({ path: join(SHOTS, `file-${path ? 'fields' : 'preview'}-400.png`), fullPage: true });
        }
        check('6 at 400 px the file page does not scroll sideways', Object.values(widths).every((w) => w <= 400), widths);
      });

      await step('7 beside the PDF each field is one line with its quote under it, the guessed one marked Check', async () => {
        await page.goto(fileUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('document-viewer').getByTestId('viewer-page-1').locator('img').waitFor({ timeout: 60_000 });
        const list = page.getByTestId('file-field-list');
        await list.waitFor();
        const caseRow = list.getByTestId('side-field-case_no');
        const caseLines = await caseRow.evaluate((el) => {
          const value = el.querySelector('span.truncate:not(.uppercase)');
          return value ? Math.round(value.getBoundingClientRect().height / parseFloat(getComputedStyle(value).lineHeight || '20')) : -1;
        });
        const quoteTitle = await caseRow.locator('p[title]').getAttribute('title');
        const garnishee = await list.getByTestId('side-field-garnishee').getAttribute('data-needs-review');
        const agency = await list.getByTestId('side-field-issuing_agency').innerText();
        await page.waitForTimeout(2500);
        await page.screenshot({ path: join(SHOTS, 'file-preview-1280.png') });
        check('7 beside the PDF each field is one line with its quote under it, the guessed one marked Check', caseLines === 1 && quoteTitle === 'SYN-2026-0012' && garnishee === 'true' && agency.includes('Not on the page') && !agency.includes('%'), { caseLines, quoteTitle, garnishee, agency });
      });

      await step('8 a field and its box on the page select each other; a value not on the page has no box', async () => {
        const viewer = page.getByTestId('document-viewer');
        const caseBox = viewer.locator('[data-box-key="case_no"]').first();
        await caseBox.waitFor({ timeout: 30_000 });
        await caseBox.click();
        const listPicked = await page.getByTestId('side-field-case_no').getAttribute('aria-pressed');
        await page.getByTestId('side-field-court').click();
        const boxPicked = await viewer.locator('[data-box-key="court"]').first().getAttribute('data-selected');
        const garnisheeBoxes = await viewer.locator('[data-box-key="garnishee"]').count();
        await page.screenshot({ path: join(SHOTS, 'file-preview-boxes-1280.png') });
        check('8 a field and its box on the page select each other; a value not on the page has no box', listPicked === 'true' && boxPicked === 'true' && garnisheeBoxes === 0, { listPicked, boxPicked, garnisheeBoxes });
      });

      await step('9 a person corrects a value on Fields, and the value as read stays beside it', async () => {
        await page.goto(`${fileUrl}/fields`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('fields-edit').click();
        await page.getByLabel('Garnishee for Record 1').fill('Harbor & Pine Bank Test Intake');
        const patched = page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/fields\/garnishee$/.test(r.url()), { timeout: 30_000 });
        await page.getByTestId('fields-save').click();
        const res = await patched;
        // Saved once the page leaves edit mode and reads the file's reads again.
        await page.getByTestId('fields-edit').waitFor({ timeout: 30_000 });
        const row = page.getByTestId('read-field-0-garnishee');
        await row.getByText('Harbor & Pine Bank Test Intake').waitFor({ timeout: 30_000 });
        const rowText = await row.innerText();
        const reads = await json(await fetch(`${documents}/v1/documents/extractions?fileId=${file.id}&page=1&pageSize=5`, { headers: J }));
        const g = reads.data[0].fields.garnishee;
        await page.screenshot({ path: join(SHOTS, 'file-fields-corrected-1280.png') });
        check('9 a person corrects a value on Fields, and the value as read stays beside it', res.status() === 200 && g.value === 'Harbor & Pine Bank Test Intake' && g.corrected === true && !(reads.data[0].needsReview ?? []).includes('garnishee') && !/Check/.test(rowText) && rowText.includes('Harbor & Pine Bank Test Intake') && rowText.includes('Harbor & Pine Bank'), { status: res.status(), field: g, keys: Object.keys(reads.data[0]), records: reads.data[0].records?.length, needsReview: reads.data[0].needsReview, rowText: rowText.slice(0, 160) });
      });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);
finish();
