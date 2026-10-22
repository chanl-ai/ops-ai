// uc-445 A person starts any workflow from a clear form, ui layer: docs/usecases/console/start-run-form.md (c-445).
// James (Operations) starts copies of the demo card dispute and the seeded levy notice workflows from the Workflows
// list: choosing one opens its form, labels come from the schema's titles, the card type is a choice and the notice's
// file is uploaded or picked from Files. The copies are read from the committed files at run time, so the run tests
// the schemas the demo ships. OPS_UC445_SHARED=1 drives the local shared stack (console :3016) instead of a private
// one and saves its screenshots under .codeloop/evidence/445/<OPS_UC445_PHASE, default after>/.
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SHARED = process.env.OPS_UC445_SHARED === '1';
const agents = `http://127.0.0.1:${SHARED ? 8700 : AGENTS_PORT}`;
const platform = `http://127.0.0.1:${SHARED ? 8710 : PLATFORM_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PDF = join(ROOT, 'services/documents-service/tests/fixtures/restraining/TEST012.pdf');
// Screenshots are the card's evidence only from the shared stack; a private run keeps them in its own temp folder.
const SHOTS = SHARED ? join(ROOT, '.codeloop/evidence/445', process.env.OPS_UC445_PHASE ?? 'after') : mkdtempSync(join(tmpdir(), 'uc445-'));
const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

/** The two workflows as the demo and the seed ship them, under this use case's ids and names. */
function copies(agentId) {
  const dispute = JSON.parse(readFileSync(join(ROOT, 'scripts/demo/workflows/card_dispute_intake.json'), 'utf8').replaceAll('{agent:dispute}', agentId));
  const seeded = JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).find((w) => w.id === 'mail_document');
  const { teamId: _team, ...notice } = structuredClone(seeded);
  // The seed marks the notice read as started only by the email intake (c-466); this use case starts it by hand.
  for (const n of notice.nodes) if (n.type === 'ops.trigger.request') delete n.parameters.onlyFromWorkflows;
  return {
    dispute: { ...dispute, id: 'uc445_dispute', name: 'Card dispute intake (uc-445)' },
    notice: { ...notice, id: 'uc445_notice', name: 'Mailed document (uc-445)' },
  };
}

async function body(consoleUrl) {
  const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
  const agentList = await (await fetch(`${agents}/v1/agents?pageSize=1`, { headers: J })).json();
  const agentId = agentList.data?.data?.[0]?.id;
  if (!agentId) throw new Error(`setup: no agent in Operations: ${JSON.stringify(agentList).slice(0, 300)}`);
  const wf = copies(agentId);
  for (const definition of Object.values(wf)) {
    const res = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition }) });
    if (res.status >= 300) throw new Error(`setup: saving ${definition.id} answered ${res.status} ${(await res.text()).slice(0, 300)}`);
  }
  mkdirSync(SHOTS, { recursive: true });
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

    // Start run: <name> for a trigger with a start form (c-466), Start a run of <name> before it.
    const form = page.getByRole('dialog', { name: /^Start a run(:| of)/ });
    const shot = async (name) => {
      for (const width of [1280, 400]) {
        await page.setViewportSize({ width, height: 900 });
        await page.waitForTimeout(500);
        await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`) });
      }
      await page.setViewportSize({ width: 1280, height: 900 });
    };

    /** Start a run on the Workflows list, choose `name` in the picker; true when the form opened with no other click. */
    const openForm = async (name) => {
      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
      const picker = page.getByRole('dialog', { name: 'Start a run' });
      await picker.waitFor();
      await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
      await page.getByPlaceholder('Search workflows', { exact: true }).fill(name);
      await page.getByRole('option', { name: new RegExp(name.replace(/[()]/g, '\\$&')) }).first().click();
      // What the person sees right after choosing: the form, or a picker still waiting for another click.
      await page.waitForTimeout(800);
      await page.screenshot({ path: join(SHOTS, 'after-choosing-1280.png') });
      const direct = await form.waitFor({ timeout: 15_000 }).then(() => true, () => false);
      if (!direct) {
        await picker.getByTestId('start-run-next').click();
        await form.waitFor();
      }
      return { direct, nextButton: direct ? 0 : 1 };
    };

    /** Test run from the open form; the request body the console sent and the run the server stored. */
    const startTest = async () => {
      await form.getByRole('radio', { name: /Test run/ }).click();
      const started = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/runs(\/start)?$/.test(r.url()), { timeout: 60_000 });
      await form.getByTestId('definition-start-run-submit').click();
      const res = await started;
      const body = JSON.parse(res.request().postData() ?? '{}');
      // POST /v1/runs/start sends the form as `values` (c-466); POST /v1/runs sent it as `input`.
      const sent = { ...body, input: body.values ?? body.input };
      const runId = (await res.json()).data?.runId;
      const run = runId ? (await (await fetch(`${agents}/v1/runs/${runId}`, { headers: J })).json()).data : null;
      return { status: res.status(), sent, run };
    };

    const labels = async () => (await form.locator('label').allInnerTexts()).map((t) => t.trim()).filter(Boolean);

    await step('1 choosing the dispute opens its form at once, named in words, card type a choice; the run gets the value', async () => {
      const opened = await openForm(wf.dispute.name);
      check('1a choosing a workflow opens its form with no other click', opened.direct, opened);
      const seen = await labels();
      const cardType = form.locator('#run-cardType');
      const isChoice = (await cardType.getAttribute('role')) === 'combobox';
      check('1b labels come from the schema titles', seen.some((t) => t.startsWith('Last four digits of SSN')) && seen.some((t) => t.startsWith('Card type')) && !seen.some((t) => /Ssn last4/.test(t)), { seen });
      await shot('dispute-form');
      await form.locator('#run-cardholder').fill('Jordan Whitfield');
      await form.locator('#run-ssnLast4').fill('5555');
      await form.locator('#run-merchant').fill('Northline Electronics');
      await form.locator('#run-amount').fill('482.10');
      await form.locator('#run-postedOn').fill('2026-10-11');
      await form.locator('#run-reason').fill('The parcel never arrived and the store stopped answering.');
      let options = [];
      if (isChoice) {
        await cardType.click();
        options = (await page.getByRole('option').allInnerTexts()).map((t) => t.trim());
        await page.getByRole('option', { name: 'Debit card' }).click();
      }
      check('1c card type is a choice of Debit card or Credit card', isChoice && options.includes('Debit card') && options.includes('Credit card'), { isChoice, options });
      await shot('dispute-filled');
      if (!isChoice) return;
      const { status, sent, run } = await startTest();
      check('1d the run receives the choice by its value', status < 300 && sent.input?.cardType === 'debit' && run?.input?.cardType === 'debit' && run?.input?.ssnLast4 === '5555', { status, input: sent.input, runInput: run?.input });
    });

    let uploaded = null;
    await step('2 the notice uploads its file and the run gets the bare id', async () => {
      await openForm(wf.notice.name);
      const seen = await labels();
      const field = form.getByTestId('run-files-fileId');
      const hasPicker = (await field.count()) === 1 && (await form.getByTestId('run-files-fileId-pick').count()) === 1;
      check('2a the notice file is an upload and a picker of Files, named in words', hasPicker && !seen.includes('File ID'), { seen, hasPicker });
      await shot('notice-form');
      if (!hasPicker) return;
      await form.locator('#run-from').fill('levies@courts.example');
      await form.locator('#run-mailbox').fill('legal-orders@harborpine.example');
      await form.locator('input[type="file"]').first().setInputFiles(PDF);
      await form.getByText('TEST012.pdf').first().waitFor({ timeout: 60_000 });
      await shot('notice-uploaded');
      const { status, sent, run } = await startTest();
      uploaded = typeof sent.input?.fileId === 'string' ? sent.input.fileId : null;
      check('2b an uploaded file reaches the run as its bare id', status < 300 && /^fil_/.test(uploaded ?? '') && run?.input?.fileId === uploaded, { status, input: sent.input, runInput: run?.input });
    });

    await step('3 the notice picks a file already in Files and the run gets its id', async () => {
      if (!uploaded) return check('3 the notice picks a file already in Files and the run gets its id', false, 'no uploaded file from step 2');
      await openForm(wf.notice.name);
      await form.locator('#run-from').fill('levies@courts.example');
      await form.locator('#run-mailbox').fill('legal-orders@harborpine.example');
      await form.getByTestId('run-files-fileId-pick').getByRole('button', { name: /Pick a file from Files/ }).click();
      await page.getByPlaceholder('Search files', { exact: true }).fill('TEST012');
      await page.getByRole('option', { name: /TEST012\.pdf/ }).first().click();
      await shot('notice-picked');
      const { status, sent, run } = await startTest();
      check('3 the notice picks a file already in Files and the run gets its id', status < 300 && typeof sent.input?.fileId === 'string' && /^fil_/.test(sent.input.fileId) && run?.input?.fileId === sent.input.fileId, { status, input: sent.input, runInput: run?.input });
    });
    check('no page errors', errors.length === 0, errors.slice(0, 3));
  } finally {
    await browser.close();
  }
}

if (SHARED) await body('http://localhost:3016');
else await withUiStack(body, { platform: true });
finish();
