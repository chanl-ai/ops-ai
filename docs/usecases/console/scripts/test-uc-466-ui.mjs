// uc-466 A person starts a workflow from its trigger's start form, ui layer: docs/usecases/console/start-from-the-trigger.md
// (c-466). The demo stack with platform sign-in and a worker. James saves copies of the court order notice workflows (the
// email intake, the document read and the debtor case, the last two marked as started only by other workflows), then:
// 1 the Start run picker offers the intake and neither child; 2 choosing it opens Send a test email, he attaches the
// court order notice PDF and sends it, and the run gets the email input a mailbox email gets and reaches a Human Task;
// 3 in Files the notice's menu starts a workflow with the file, offering only the intake, whose test email opens with
// the notice attached; 5 uploading the same PDF again under Chat attachment reuses the stored file. UC466_ONLY takes
// step numbers as a pattern: 5 runs step 5 alone (its red run without the upload fix), '1|2|3' skips step 5.
// Screenshots go to .codeloop/evidence/466/uc/.
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const PDF = join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice.pdf');
const SEED = Object.fromEntries(JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).map((w) => [w.id, w]));
// The run input an Email received trigger gives every run (ops_engine shapes.EMAIL).
const EMAIL_KEYS = ['attachments', 'body', 'bodyFile', 'folder', 'from', 'mailbox', 'messageId', 'receivedAt', 'skipped', 'subject'];
const SHOTS = join(ROOT, '.codeloop/evidence/466/uc');
const ONLY = process.env.UC466_ONLY;

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 120_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

/** The three seeded workflows under this use case's ids and names, each starting the next by its copy's id. */
function copies() {
  const ids = { mail_intake: 'uc466_intake', mail_document: 'uc466_document', levy_case: 'uc466_case' };
  const names = { mail_intake: 'Court order notices by email (uc-466)', mail_document: 'Court order notice: read (uc-466)', levy_case: 'Court order notice: one debtor (uc-466)' };
  return Object.keys(ids).map((seed) => {
    const { teamId: _team, ...d } = structuredClone(SEED[seed]);
    for (const n of d.nodes) if (n.type === 'ops.action.workflow' && ids[n.parameters.workflow]) n.parameters.workflow = ids[n.parameters.workflow];
    return { ...d, id: ids[seed], name: names[seed] };
  });
}

async function step(name, body) {
  if (ONLY && !new RegExp(`^(${ONLY}) `).test(name)) return;
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    for (const definition of copies()) {
      const res = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ definition }) });
      if (res.status >= 300) throw new Error(`setup: saving ${definition.id} answered ${res.status} ${(await res.text()).slice(0, 300)}`);
    }
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      const shot = async (name) => {
        for (const width of [1280, 400]) {
          await page.setViewportSize({ width, height: 900 });
          await page.waitForTimeout(500);
          await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`) });
        }
        await page.setViewportSize({ width: 1280, height: 900 });
      };
      const picker = page.getByRole('dialog', { name: /^Start a (run|workflow with this file)$/ });
      const composer = page.getByRole('dialog', { name: /^Send a test email: Court order notices by email \(uc-466\)/ });
      /** The workflows the open picker offers for a search. */
      const offered = async (search) => {
        await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
        await page.getByPlaceholder('Search workflows', { exact: true }).fill(search);
        // The search runs on the server: wait for its rows (or its empty answer) before reading them.
        await page.getByRole('option').or(page.getByText('Nothing matches.')).first().waitFor({ timeout: 30_000 }).catch(() => undefined);
        await page.waitForTimeout(500);
        return (await page.getByRole('option').allInnerTexts()).map((t) => t.trim());
      };

      let runId = null;
      await step('1 the Start run picker offers the email intake and neither workflow only other workflows start', async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
        await picker.waitFor();
        const seen = await offered('uc-466');
        check('1 the Start run picker offers the email intake and neither workflow only other workflows start', seen.some((t) => t.includes('Court order notices by email')) && !seen.some((t) => t.includes(': read (uc-466)') || t.includes('one debtor (uc-466)')), { seen });
        await shot('picker');
      });

      await step('2 a test email with the court order notice runs as a mailbox email does and reaches a Human Task', async () => {
        await page.getByRole('option', { name: /Court order notices by email/ }).first().click();
        await composer.waitFor();
        const labels = (await composer.locator('label').allInnerTexts()).map((t) => t.trim());
        check('2a choosing it opens Send a test email: From, Subject, Body and Attachments, no file id box', ['From', 'Subject', 'Body', 'Attachments'].every((l) => labels.some((t) => t.startsWith(l))) && !labels.some((t) => /File ID|Mailbox/.test(t)), { labels });
        await composer.getByRole('radio', { name: /Test run/ }).click();
        await composer.locator('#run-from').fill('registry@court.example');
        await composer.locator('#run-subject').fill('Notice of levy, case 2026-CV-1182');
        await composer.locator('#run-body').fill('Please find the notice attached.');
        await composer.locator('input[type="file"]').first().setInputFiles(PDF);
        await composer.getByText('levy_notice.pdf').first().waitFor({ timeout: 60_000 });
        await composer.getByText(/Uploaded · scan clean|Already stored in your team · reused/).first().waitFor({ timeout: 60_000 });
        await page.waitForTimeout(1000);
        const shown = await composer.getByTestId('run-files-attachments').getByText('levy_notice.pdf', { exact: true }).count();
        check('2e the attached notice shows once, with its status and a remove button', shown === 1 && (await composer.getByRole('button', { name: 'Remove levy_notice.pdf' }).count()) === 1, { shown });
        await shot('composer-filled');
        const started = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/runs\/start$/.test(r.url()), { timeout: 60_000 });
        await composer.getByTestId('definition-start-run-submit').click();
        const res = await started;
        runId = (await res.json()).data?.runId ?? null;
        const run = runId ? await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: james })) : null;
        const input = run?.input ?? {};
        const [attachment] = input.attachments ?? [];
        check('2b the run gets the email input a mailbox email gives, the notice stored in Files', res.status() === 202 && JSON.stringify(Object.keys(input).sort()) === JSON.stringify(EMAIL_KEYS) && attachment?.name === 'levy_notice.pdf' && /^fil_/.test(attachment?.fileId ?? '') && attachment?.mime === 'application/pdf' && input.bodyFile?.name === 'email-body.txt' && !!input.mailbox, { status: res.status(), keys: Object.keys(input), attachment, bodyFile: input.bodyFile, mailbox: input.mailbox });
        check('2c the run says James sent it as a test email', run?.startedBy?.via?.name === 'test email' && /richardson/i.test(`${run?.startedBy?.id} ${run?.startedBy?.name}`), run?.startedBy);
        // The notice is read in a child run (the intake waits for it); a person then has a Human Task in a child.
        const waiting = await until(async () => {
          for (const wid of ['uc466_document', 'uc466_case']) {
            const listed = (await json(await fetch(`${agents}/v1/runs?workflowId=${wid}&pageSize=50`, { headers: james }))).data ?? [];
            for (const w of listed.filter((r) => r.status === 'waiting')) {
              const review = await (await fetch(`${agents}/reviews/${w.id}`, { headers: james })).json();
              if (review.data?.id) return { workflow: wid, runId: w.id, review: review.data.title ?? review.data.question };
            }
          }
          return null;
        }, 240_000);
        const family = [];
        if (!waiting) for (const wid of ['uc466_intake', 'uc466_document', 'uc466_case']) for (const r of (await json(await fetch(`${agents}/v1/runs?workflowId=${wid}&pageSize=50`, { headers: james }))).data ?? []) family.push({ wid, status: r.status, error: r.error, waiting: r.waiting?.node });
        check('2d the notice reaches a Human Task', !!waiting, waiting ?? family);
        await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(2500);
        await shot('run');
      });

      await step('3 Files starts a workflow with the notice: only file-taking workflows, and the email opens with it attached', async () => {
        await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByPlaceholder(/^Search names/).fill('levy_notice');
        const row = page.locator('table tbody tr').filter({ hasText: 'levy_notice.pdf' }).first();
        await row.waitFor({ timeout: 120_000 });
        await row.getByRole('button', { name: 'Open menu' }).click();
        await shot('files-menu');
        await page.getByRole('menuitem', { name: 'Start a workflow with this file' }).click();
        await picker.waitFor();
        const seen = await offered('uc-466');
        check('3a only workflows a file starts and a person starts are offered', seen.some((t) => t.includes('Court order notices by email')) && seen.length === 1, { seen });
        await page.getByRole('option', { name: /Court order notices by email/ }).first().click();
        await composer.waitFor();
        await page.waitForTimeout(1500);
        const field = composer.getByTestId('run-files-attachments');
        const attached = await field.innerText();
        const shown = await field.getByText('levy_notice.pdf', { exact: true }).count();
        check('3b the test email opens with the notice attached, shown once', shown === 1 && (await composer.getByRole('button', { name: 'Remove levy_notice.pdf' }).count()) === 1, { shown, attached: attached.slice(0, 200) });
        await shot('file-start-composer');
        await composer.getByRole('button', { name: 'Cancel' }).click();
      });

      await step('5 the same PDF uploaded again under another purpose reuses the stored file', async () => {
        await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        if (ONLY) {
          // On its own, the step first stores the notice as an Email attachment, as step 2's upload does.
          const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: james, body: JSON.stringify({ name: 'levy_notice.pdf', size: readFileSync(PDF).length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
          await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...james, 'Content-Type': 'application/pdf' }, body: readFileSync(PDF) });
          await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: james });
        }
        await page.getByTestId('files-upload').click();
        const dialog = page.getByRole('dialog', { name: 'Upload files' });
        await dialog.waitFor();
        await dialog.getByRole('combobox').first().click();
        await page.getByRole('option', { name: 'Chat attachment' }).click();
        await dialog.locator('input[type="file"]').first().setInputFiles(PDF);
        const outcome = dialog.getByText(/Already stored in your team · reused|Uploaded · scan clean|not found|refused|failed/i).first();
        // What the dialog says about the file once it settles: reused, uploaded, or the error it ended in.
        const text = await outcome.waitFor({ timeout: 60_000 }).then(() => outcome.innerText(), async () => (await dialog.innerText()).replace(/\s+/g, ' ').slice(-300));
        await shot('upload-again');
        check('5 the same PDF uploaded again under another purpose reuses the stored file', /Already stored in your team · reused/.test(text), { text });
      });
      check('6 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
