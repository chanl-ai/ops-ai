// uc-249 a complaint email is triaged, ui layer: docs/usecases/agents-service/a-complaint-email-is-triaged-attachments.md.
// The seeded complaint_triage workflow on the banker demo stack: platform sign-in, models on the fake OpenAI with the
// demo's rules, tools-service with the core fake bank, GreenMail and Mailpit reachable (tools.mail), the seeded
// mailboxes, and a worker. Run isolated (ISOLATED=1). Real mail both ways; nothing else faked but the bank and the model.
// The receipt's document type is configuration made here through the documents API, as a team would on its page.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { AGENTS_PORT, DOCUMENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const documents = `http://127.0.0.1:${DOCUMENTS_PORT}`;
const MAILPIT = `http://127.0.0.1:${process.env.OPS_MAILPIT_HTTP_PORT ?? 8025}`;
const GREENMAIL_SMTP = process.env.OPS_GREENMAIL_SMTP_PORT ?? '3025';
const PASSWORD = 'northfield-demo';
const MAILBOX = 'complaints@harborpine.test';
// The seeded bank's customer: the complaint comes from the address the bank holds for them, which is how the hold's
// Match step knows them without the last four of their SSN.
const CUSTOMER = 'marcus.bell@example.com';
const SETTLED = ['succeeded', 'failed', 'cancelled'];
const RECEIPT_TYPE = {
  id: 'payment_receipt',
  name: 'Payment receipt',
  description: 'A receipt for a payment a customer made: who paid, how much, when, and its reference.',
  many: false,
  fields: [
    { key: 'payer_name', label: 'Payer', type: 'text', required: true },
    { key: 'amount', label: 'Amount', type: 'money', required: true },
    { key: 'paid_on', label: 'Paid on', type: 'date' },
    { key: 'reference', label: 'Reference', type: 'text' },
  ],
};

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team = 'team_ops') => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const get = async (url, h) => (await (await fetch(url, { headers: h })).json()).data;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(probe, seconds = 120) {
  for (const end = Date.now() + seconds * 1000; Date.now() < end; await sleep(1000)) {
    const got = await probe().catch(() => undefined);
    if (got) return got;
  }
  return undefined;
}
async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}
// The steps a run passed, in order, with the port each left by.
const path = (run) => (run?.steps ?? []).map((s) => `${s.nodeId}:${s.port ?? s.status}`);
const has = (run, want) => want.filter((s) => !path(run).includes(s));

// A complaint with a one-page payment receipt attached, sent by SMTP to GreenMail. The receipt is drawn the same way
// every time (reportlab's invariant mode), so its bytes do not change between runs.
function sendComplaint() {
  const script = `
import io, smtplib, sys
from email.message import EmailMessage
from reportlab import rl_config
rl_config.invariant = 1
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
buf = io.BytesIO()
c = Canvas(buf, pagesize=LETTER)
for y, line in zip(range(720, 560, -28), ["Payment receipt", "Payer: Marcus Bell", "Amount paid: CAD 2,000.00", "Paid on: 2026-09-30", "Reference: RECEIPT-UC249"]):
    c.drawString(72, y, line)
c.save()
m = EmailMessage()
m["From"] = "Marcus Bell <${CUSTOMER}>"
m["To"] = sys.argv[1]
m["Subject"] = "Money frozen on my account"
m["Message-ID"] = "<complaint-uc249@example.com>"
m.set_content("COMPLAINT-UC249\\nMy name is Marcus Bell. You froze money on my account over a debt I already paid. "
              "I paid it on 30 September, receipt attached. Please hold the 2,000.00 until this is sorted out.")
m.add_attachment(buf.getvalue(), maintype="application", subtype="pdf", filename="receipt.pdf")
with smtplib.SMTP("127.0.0.1", int(sys.argv[2])) as s:
    s.send_message(m)
`;
  execFileSync('uv', ['run', '--quiet', 'python', '-c', script, MAILBOX, GREENMAIL_SMTP], { cwd: join(ROOT, 'services/documents-service'), stdio: 'pipe' });
}

await withUiStack(
  async (consoleUrl, stack) => {
    const S = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
    const J = as(await tokenFor('j.richardson@harborpine.example'));
    // The reply goes out through send_reply on the Messaging Platform team's mail module, so that team approves it.
    const W = as(await tokenFor('w.kamau@harborpine.example'), 'team_platform');
    const M = as(await tokenFor('m.okafor@harborpine.example'));
    const P = as(await tokenFor('p.shah@harborpine.example'));
    const runsOf = async (workflow) => (await get(`${agents}/v1/runs?workflowId=${workflow}&pageSize=50`, J))?.data ?? [];
    const detail = (id) => get(`${agents}/v1/runs/${id}`, J);
    const out = (run, node) => (run?.steps ?? []).find((s) => s.nodeId === node)?.output;

    // 0. Security stores the mailbox secret and allows the mail hosts; the team adds its receipt document type.
    await step('0 the mailbox secret, the mail hosts and the receipt type are set up', async () => {
      const secret = await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: 'DEV_IMAP_PASSWORD', value: 'any', teams: ['team_ops'] }) });
      const allowed = [];
      for (const value of [stack.mail.imapHost, stack.mail.smtpHost]) allowed.push((await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value, note: 'uc-249' }) })).status);
      allowed.push((await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.mail.range, note: 'uc-249' }) })).status);
      const type = await fetch(`${documents}/v1/document-types`, { method: 'POST', headers: J, body: JSON.stringify(RECEIPT_TYPE) });
      check('0 the mailbox secret, the mail hosts and the receipt type are set up', secret.status === 201 && allowed.every((s) => s === 201 || s === 200) && type.status === 201, { secret: secret.status, allowed, type: type.status === 201 ? 201 : await type.text() });
    });

    const worker = await stack.startWorker({ OPS_EMAIL_POLL_SECONDS: '1', OPS_ENGINE_POLL_SECONDS: '0.2' });
    await sleep(31_000); // agents-service keeps each tenant's tool list for 30 seconds; the first pass syncs

    // 1. Email received, Switch (attachments), Run workflow for each, Extract with fields, Combine, Agent with an
    // output schema, Switch (urgency), Set fields, If (no case quoted), Open case, If (hold asked), Run workflow once,
    // Human review: the run waits for the reply's approval.
    let run;
    await step('1 the complaint is read, triaged, a case opened and a hold started; the reply waits for approval', async () => {
      sendComplaint();
      run = await until(async () => (await runsOf('complaint_triage')).find((r) => r.status === 'waiting' || SETTLED.includes(r.status)), 180);
      run = run && (await detail(run.id));
      const want = ['mail:payload', 'what:attachments', 'each:started', 'combine:out', 'triage:ok', 'urgency:high', 'urgent:out', 'has_case:false', 'open:opened', 'wants_hold:true', 'hold_once:started'];
      const read = path(run).find((s) => s.startsWith('read_body:'));
      check('1 the complaint is read, triaged, a case opened and a hold started; the reply waits for approval', run?.status === 'waiting' && (run.waiting ?? {}).node === 'ack' && has(run, want).length === 0 && ['read_body:ok', 'read_body:review'].includes(read), { status: run?.status, waiting: run?.waiting?.node, missing: has(run, want), read, steps: path(run) });
    });

    // 2. The child run per attachment: Extract with Detect recognises the receipt, Save data on file keeps the read.
    await step('2 the attachment is recognised as a payment receipt and its read kept on the file', async () => {
      const child = await until(async () => (await runsOf('attachment_record')).find((k) => k.startedBy?.runId === run?.id && SETTLED.includes(k.status)));
      const done = child && (await detail(child.id));
      const read = out(done, 'read');
      const saved = out(done, 'save');
      check('2 the attachment is recognised as a payment receipt and its read kept on the file', done?.outcome === 'recorded' && has(done, ['start:payload', 'read:ok', 'save:ok']).length === 0 && read?.documentType?.id === 'payment_receipt' && saved?.data?.typeId === 'payment_receipt', { outcome: done?.outcome, steps: path(done), type: read?.documentType, saved: saved?.data });
    });

    // 3. The agent's structured answer drives the priority and lands on the new case.
    await step('3 the agent triages it urgent and the case carries the triage', async () => {
      const triage = out(run, 'triage');
      const caseId = out(run, 'open')?.caseId;
      const opened = caseId ? await get(`${agents}/v1/cases/${caseId}`, J) : undefined;
      check('3 the agent triages it urgent and the case carries the triage', triage?.urgency === 'high' && triage?.wantsHold === true && opened?.priority === 'urgent' && opened?.fields?.category === triage?.category && !!opened?.fields?.complaint, { triage, priority: opened?.priority, fields: opened?.fields });
    });

    // 4. Run workflow once started customer_hold for the sender: matched by their address and waiting for approval.
    // The run page masks the address people read (c-321); the matched customer's name is not masked, and step 5's mail
    // to the real address proves the workflow kept it.
    await step('4 the hold it started found the customer by their address and waits for approval', async () => {
      const hold = await until(async () => (await runsOf('customer_hold')).find((k) => k.startedBy?.runId === run?.id && (k.status === 'waiting' || SETTLED.includes(k.status))));
      const held = hold && (await detail(hold.id));
      check('4 the hold it started found the customer by their address and waits for approval', (held?.waiting ?? {}).node === 'review' && has(held, ['search:ok', 'match:matched', 'calc:out', 'enough:true']).length === 0 && out(held, 'calc')?.hold === 2000 && out(held, 'match')?.match?.name === 'Marcus Bell', { status: held?.status, waiting: held?.waiting?.node, steps: path(held), calc: out(held, 'calc') });
    });

    // 5. Human review approved by the mail module's team, then Call a tool (send_reply) and End.
    await step('5 the approved reply leaves from the complaints mailbox', async () => {
      const replies = async () => {
        const found = await (await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${CUSTOMER}"`)}`)).json();
        return (found.messages ?? []).filter((m) => m.From.Address === MAILBOX).length;
      };
      const before = await replies(); // an earlier run on this Mailpit may have replied to the same address
      const ack = await fetch(`${agents}/reviews/${run.id}/decision`, { method: 'POST', headers: W, body: JSON.stringify({ decision: 'approved', reason: 'uc-249' }) });
      // Its own steps end at Replied, but the run it started still waits on a person, so it is not done.
      const done = await until(async () => {
        const r = await detail(run.id);
        return r?.outcome ? r : undefined;
      }, 60);
      const after = await until(async () => ((await replies()) > before ? await replies() : undefined), 60);
      check('5 the approved reply leaves from the complaints mailbox', ack.status === 200 && done?.outcome === 'replied' && done?.status === 'waiting' && !done?.finishedAt && has(done, ['ack:approve', 'reply:ok']).length === 0 && after === before + 1, { ack: ack.status === 200 ? 200 : await ack.text(), status: done?.status, outcome: done?.outcome, steps: path(done), before, after });
    });

    // 6. The hold it started is approved by two people, each re-authenticating; then the complaint is done.
    await step('6 once its hold is placed the complaint run succeeds', async () => {
      const hold = (await runsOf('customer_hold')).find((k) => k.startedBy?.runId === run?.id);
      // While the hold waits, the complaint's page says it waits on a run it started.
      const browser = await chromium.launch();
      let waitingOn;
      try {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill('j.richardson@harborpine.example');
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/workflows/runs/${run.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        waitingOn = (await page.getByTestId('run-waiting-on-runs').innerText({ timeout: 60_000 })).trim();
      } finally {
        await browser.close();
      }
      const codes = [];
      for (const who of [M, P]) {
        if (((await detail(hold.id))?.waiting ?? {}).node !== 'review') break;
        const stepUp = (await (await fetch(`${agents}/v1/auth/step-up`, { method: 'POST', headers: who, body: JSON.stringify({ password: PASSWORD }) })).json()).data?.token;
        const res = await fetch(`${agents}/reviews/${hold.id}/decision`, { method: 'POST', headers: who, body: JSON.stringify({ decision: 'approved', reason: 'uc-249', stepUpToken: stepUp }) });
        codes.push(res.status === 200 ? 200 : `${res.status} ${(await res.text()).slice(0, 300)}`);
        await sleep(1500);
      }
      const held = await until(async () => {
        const r = await detail(hold.id);
        return SETTLED.includes(r?.status) ? r : undefined;
      }, 60);
      const parent = await until(async () => {
        const r = await detail(run.id);
        return SETTLED.includes(r?.status) ? r : undefined;
      }, 30);
      check('6 once its hold is placed the complaint run succeeds', waitingOn?.startsWith('Waiting on a run it started') && held?.outcome === 'held' && parent?.status === 'succeeded' && parent?.outcome === 'replied' && !!parent?.finishedAt, { waitingOn, codes, hold: held?.outcome, status: parent?.status, outcome: parent?.outcome });
    });

    // 7. An End marked as a failure: the run reads failed with where it ended, in the list, on its page, in the editor.
    await step('7 a run that ends at a failure End reads failed in the list, on its page and in the editor', async () => {
      const id = (await (await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: 'attachment_record', mode: 'live', input: { fileId: 'fil_missing_uc249', name: 'missing.pdf' } }) })).json()).data?.runId;
      const ended = await until(async () => {
        const r = await detail(id);
        return SETTLED.includes(r?.status) ? r : undefined;
      }, 60);
      const row = (await runsOf('attachment_record')).find((r) => r.id === id);
      const browser = await chromium.launch();
      const shown = {};
      const errors = [];
      try {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill('j.richardson@harborpine.example');
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/workflows/runs/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        shown.alert = (await page.getByRole('alert').filter({ hasText: 'The run failed' }).first().innerText({ timeout: 60_000 })).trim();
        shown.result = await page.getByTestId('run-result').getAttribute('data-outcome');
        await page.goto(`${consoleUrl}/workflows/definitions/attachment_record`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('[data-testid="definition-node"][data-node-id="failed"]').dblclick({ timeout: 60_000 });
        shown.end = (await page.locator('[data-field$="-result"]').first().innerText({ timeout: 30_000 })).trim();
      } finally {
        await browser.close();
      }
      const why = 'Ended at Could not finish, an end marked as a failure';
      check('7 a run that ends at a failure End reads failed in the list, on its page and in the editor', ended?.status === 'failed' && has(ended, ['start:payload', 'read:error']).length === 0 && ended?.outcome === 'failed' && row?.status === 'failed' && row?.error === why && shown.alert?.includes(why) && shown.result === 'failed' && shown.end === 'Failed' && errors.length === 0, { status: ended?.status, steps: path(ended), row: row && { status: row.status, error: row.error }, shown, errors });
    });

    // 8. Activity filtered to the complaint's case: its own entries and what its run did, nothing of the hold's run.
    await step('8 the activity of the case is its entries, its run, the email that started it and the decision on it', async () => {
      const caseId = out(run, 'open')?.caseId;
      const listed = caseId ? await get(`${agents}/v1/activity?case=${caseId}&pageSize=100`, J) : undefined;
      const rows = listed?.data ?? [];
      const kinds = new Set(rows.map((r) => r.kind));
      const refs = new Set(rows.filter((r) => r.kind !== 'case').map((r) => r.ref.id));
      const held = (await runsOf('customer_hold')).find((k) => k.startedBy?.runId === run?.id)?.id;
      const want = ['case', 'workflow_run', 'email', 'decision'];
      check(
        '8 the activity of the case is its entries, its run, the email that started it and the decision on it',
        want.every((k) => kinds.has(k)) && refs.size === 1 && refs.has(run.id) && (!held || !refs.has(held)),
        { kinds: [...kinds], refs: [...refs], held, titles: rows.filter((r) => r.kind === 'case').map((r) => r.title) },
      );
    });

    await worker.stop();
  },
  { demo: true, tools: { mail: true }, agentsEnv: { OPS_MAILBOXES_SEED_FILE: 'seed/mailboxes.json' } },
);

finish();
