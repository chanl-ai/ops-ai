// uc-245 a team's mailbox runs end to end, ui layer: docs/usecases/agents-service/a-team-s-mailbox-runs-end.md (c-230,
// epic c-227). withUiStack on the banker demo (platform sign-in, models on the fake OpenAI with the demo's committed
// rules, tools-service with the core fake bank), GreenMail and Mailpit reachable through tools-service (tools.mail),
// publish reviews kept pending, and a worker. Run isolated (ISOLATED=1). Real mail both ways: the script sends SMTP to
// GreenMail and reads the reply in Mailpit's API; nothing else is faked but the bank and the model.
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { decideInConsole } from '../../lib/workflow_ui.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const MAILPIT = `http://127.0.0.1:${process.env.OPS_MAILPIT_HTTP_PORT ?? 8025}`;
const GREENMAIL_SMTP = process.env.OPS_GREENMAIL_SMTP_PORT ?? '3025';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const PRIYA = 'p.shah@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
// The reply goes out through send_reply on the Messaging Platform team's mail module, so that team approves the write.
const PASSWORD = 'northfield-demo';
const SECRET = 'INTAKE_MAIL_PASSWORD';
const RUN = Math.random().toString(36).slice(2, 8);
const ADDRESS = `intake-${RUN}@harborpine.test`;
const SENDER = `clerk-${RUN}@court.example`;
const SUBJECT = `Notice of garnishment ${RUN}`;
const MESSAGE_ID = `<uc245-${RUN}@court.example>`;
const SEED = Object.fromEntries(JSON.parse(execFileSync('cat', [join(ROOT, 'services/agents-service/seed/engine_workflows.json')], { encoding: 'utf8' })).map((w) => [w.id, w]));
const SETTLED = ['succeeded', 'failed', 'cancelled'];
// The demo seeds these workflows for another team; the team publishes its own copies under this run's ids.
const ID = Object.fromEntries(['levy_case', 'mail_document', 'mail_intake'].map((w) => [w, `${w}_${RUN}`]));

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

// A notice the model misreads (the demo rule answers a debtor the page does not name), so its read scores below the
// floor and waits on Check the read: the same page uc-223 sends. The message is built once and the same bytes are sent
// each time, so a second send is a redelivery (a new message reusing the Message-ID would run, c-231).
const EML = join(process.env.TMPDIR ?? '/tmp', `uc245-${RUN}.eml`);
function sendNotice() {
  const script = `
import io, smtplib, sys
from email.message import EmailMessage
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
out = io.BytesIO(); c = canvas.Canvas(out, pagesize=LETTER)
for i, line in enumerate(["Debtor 1: Ana Example Address: 9 Elm Street, Halifax NS SSN (last four): ***-**-1234",
                          "Amount: 100.00 Court: Nova Scotia Supreme Court Case No: NS-2026-GN-09999"]):
    c.drawString(40, 740 - 16 * i, line)
c.save()
m = EmailMessage()
m["From"], m["To"], m["Subject"], m["Message-ID"] = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
m.set_content("Please find the notice attached.")
m.add_attachment(out.getvalue(), maintype="application", subtype="pdf", filename="notice.pdf")
open(sys.argv[6], "wb").write(bytes(m))
`;
  const send = `
import smtplib, sys
with smtplib.SMTP("127.0.0.1", int(sys.argv[3])) as s:
    s.sendmail(sys.argv[1], [sys.argv[2]], open(sys.argv[4], "rb").read())
`;
  const cwd = join(ROOT, 'services/agents-service');
  if (!existsSync(EML)) execFileSync('uv', ['run', '--quiet', 'python', '-c', script, SENDER, ADDRESS, SUBJECT, MESSAGE_ID, GREENMAIL_SMTP, EML], { cwd, stdio: 'pipe' });
  execFileSync('uv', ['run', '--quiet', 'python', '-c', send, SENDER, ADDRESS, GREENMAIL_SMTP, EML], { cwd, stdio: 'pipe' });
}

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  page.setDefaultTimeout(60_000);
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function pickSecret(page, id) {
  await page.locator(`#${id}`).click();
  // The open picker's list only: a closed picker keeps its options in the page.
  await page.locator('[role="listbox"]:visible, [cmdk-list]:visible').last().getByRole('option', { name: new RegExp(SECRET) }).first().click();
}

await withUiStack(
  async (consoleUrl, stack) => {
    const S = as(await tokenFor(SAM), 'team_security');
    const J = as(await tokenFor(JAMES));
    const P = as(await tokenFor(PRIYA));
    // A held write is decided in its run's team (Operations), so Maya acknowledges, not the mail module's owners.
    const M = as(await tokenFor(MAYA));
    const runsOf = async (workflow) => (await get(`${agents}/v1/runs?workflowId=${workflow}&pageSize=100`, J))?.data ?? [];
    const detail = (id) => get(`${agents}/v1/runs/${id}`, J);
    const out = (run, node) => (run?.steps ?? []).find((s) => s.nodeId === node)?.output;

    // 0. A Security admin puts the mailbox password on the Secrets page for team_ops and allows the mail hosts.
    await step('0 Sam stores the mailbox secret and allows the mail hosts', async () => {
      const secret = await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: SECRET, value: 'app-password', teamId: 'team_ops' }) });
      const allowed = [];
      for (const value of [stack.mail.imapHost, stack.mail.smtpHost]) allowed.push((await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value, note: 'uc-245' }) })).status);
      allowed.push((await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.mail.range, note: 'uc-245' }) })).status);
      check('0 Sam stores the mailbox secret and allows the mail hosts', secret.status === 201 && allowed.every((s) => s === 201 || s === 200), { secret: secret.status, allowed });
    });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = await signIn(browser, consoleUrl, JAMES, errors);

      // 1. James connects the mailbox on Channels > Email with its own SMTP sender; Test connection is green throughout.
      await step('1 James connects the mailbox in the console and every connection test passes', async () => {
        await james.goto(`${consoleUrl}/channels/email`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByTestId('connect-mailbox').click();
        await james.getByLabel('Other IMAP').click();
        await james.getByTestId('connect-mailbox-submit').click();
        await james.locator('#connect-page-name').fill(`Intake ${RUN}`);
        await james.locator('#connect-page-address').fill(ADDRESS);
        await james.locator('#connect-page-host').fill(stack.mail.imapHost);
        await james.locator('#connect-page-port').fill('143');
        await james.locator('#connect-page-tls').click(); // GreenMail speaks plain IMAP; refused outside a dev stack
        await pickSecret(james, 'connect-page-secret');
        await james.locator('label[for="connect-page-sender-smtp"]').click();
        await james.locator('#connect-page-smtpHost').fill(stack.mail.smtpHost);
        await james.locator('#connect-page-smtpPort').fill('587');
        await pickSecret(james, 'connect-page-senderSecret');
        await james.getByTestId('mailbox-test-run').click();
        const result = james.getByTestId('mailbox-test-result');
        await result.waitFor({ timeout: 60_000 });
        const tested = { ok: await result.getAttribute('data-ok'), text: await result.innerText() };
        await james.getByTestId('connect-mailbox-submit').click();
        await james.getByTestId('mailbox-page').waitFor({ timeout: 60_000 });
        const record = ((await get(`${agents}/v1/channels/mailboxes`, J)) ?? []).find((m) => m.address === ADDRESS);
        check('1 James connects the mailbox in the console and every connection test passes', tested.ok === 'true' && record?.sender === 'smtp' && record?.fromAddress === ADDRESS, { tested, record });
        // Mailpit speaks plain SMTP and the form always asks for STARTTLS, which a real server offers.
        if (record) await fetch(`${agents}/v1/channels/mailboxes/${record.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ smtpStarttls: false }) });
      });

      // 2. James binds the levy workflows to the mailbox; each publish waits for a review until Priya approves it.
      await step('2 the workflows go live on the mailbox only after another person approves each review', async () => {
        const pending = [];
        for (const seeded of ['levy_case', 'mail_document', 'mail_intake']) {
          const name = ID[seeded];
          const d = structuredClone(SEED[seeded]);
          delete d.teamId;
          d.id = name;
          for (const n of d.nodes) {
            if (n.type === 'ops.trigger.email') n.parameters.mailbox = ADDRESS;
            if (n.parameters?.workflow in ID) n.parameters.workflow = ID[n.parameters.workflow];
          }
          const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: d }) });
          const asked = await (await fetch(`${agents}/v1/workflows/definitions/${name}/publish-requests`, { method: 'POST', headers: J, body: '{}' })).json();
          pending.push({ name, saved: saved.status, id: asked.data?.id, status: asked.data?.status ?? JSON.stringify(asked).slice(0, 200) });
        }
        const self = await fetch(`${agents}/v1/publish-requests/${pending[0].id}/decision`, { method: 'POST', headers: J, body: JSON.stringify({ decision: 'approved' }) });
        const decided = [];
        for (const p of pending) decided.push((await (await fetch(`${agents}/v1/publish-requests/${p.id}/decision`, { method: 'POST', headers: P, body: JSON.stringify({ decision: 'approved' }) })).json()).data?.status);
        check('2 the workflows go live on the mailbox only after another person approves each review', pending.every((p) => p.status === 'pending') && self.status === 403 && decided.every((s) => s === 'approved'), { pending, self: self.status, decided });
      });

      const worker = await stack.startWorker({ OPS_EMAIL_POLL_SECONDS: '1', OPS_ENGINE_POLL_SECONDS: '0.2' });
      await sleep(31_000); // agents-service keeps each tenant's tool list for 30 seconds; the first pass syncs

      // 3. A notice arrives by SMTP; one intake run starts and its PDF is stored in Files.
      let doc;
      await step('3 the email starts one intake run and its PDF is in Files', async () => {
        sendNotice();
        // The intake's own steps end once it has started the document's run; it then waits on that run.
        const intake = await until(async () => (await runsOf(ID.mail_intake)).find((r) => r.outcome || SETTLED.includes(r.status)));
        // The run's input is customer data, which the API masks ([email]), so the sender is not compared here.
        const attachments = intake?.input?.attachments ?? [];
        doc = await until(async () => (await runsOf(ID.mail_document)).find((r) => r.status === 'waiting'));
        check('3 the email starts one intake run and its PDF is in Files', attachments.length === 1 && !!attachments[0].fileId && attachments[0].name === 'notice.pdf', { intake: intake?.status, from: intake?.input?.from, attachments });
      });

      // 4. The read scores below the floor, so it waits on Check the read; Maya decides it on Human Tasks.
      await step('4 the low-confidence read waits on Check the read and Maya approves it on Human Tasks', async () => {
        const waiting = (doc?.waiting ?? {}).node;
        const maya = await signIn(browser, consoleUrl, MAYA, errors);
        const status = await decideInConsole(maya, consoleUrl, doc, 'approve');
        check('4 the low-confidence read waits on Check the read and Maya approves it on Human Tasks', waiting === 'check' && status === 200, { waiting, decision: status });
      });

      // 5. The approved read opens a levy case for the debtor; the case is on Cases.
      await step('5 the debtor’s levy run opens a case', async () => {
        const cases = await until(async () => out(await detail(doc.id), 'open'));
        const levyId = cases?.runs?.[0]?.runId;
        const levy = await until(async () => {
          const r = await detail(levyId);
          return r && (r.status === 'waiting' || SETTLED.includes(r.status)) ? r : undefined;
        });
        const caseId = (out(levy, 'case') ?? out(levy, 'case_unmatched'))?.caseId;
        const opened = caseId ? await get(`${agents}/v1/cases/${caseId}`, J) : undefined;
        // The case names the debtor as the approved read gives it.
        const debtor = levy?.input?.record?.name;
        check('5 the debtor’s levy run opens a case', !!debtor && opened?.subject?.includes(debtor) && opened.status === 'open', { levy: levy?.outcome ?? levy?.status, debtor, opened: opened?.subject });
      });

      // 6. The mail module's team acknowledges the document; the reply leaves from the mailbox's own address.
      await step('6 the acknowledgement sends one reply from the mailbox’s own address', async () => {
        await until(async () => ((await detail(doc.id))?.waiting ?? {}).node === 'ack');
        const ack = await fetch(`${agents}/reviews/${doc.id}/decision`, { method: 'POST', headers: M, body: JSON.stringify({ decision: 'approved', reason: 'uc-245' }) });
        const sent = await until(async () => {
          const found = await (await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${SENDER}"`)}`)).json();
          return (found.messages ?? []).filter((m) => m.Subject.includes(RUN)).length ? found.messages.filter((m) => m.Subject.includes(RUN)) : undefined;
        }, 60);
        // Its own steps end at Replied; it may still wait on the levy case it started.
        const done = await until(async () => {
          const r = await detail(doc.id);
          return r?.outcome ? r : undefined;
        }, 60);
        check('6 the acknowledgement sends one reply from the mailbox’s own address', ack.status === 200 && sent?.length === 1 && sent[0].From.Address === ADDRESS && done?.outcome === 'replied', { ack: ack.status === 200 ? 200 : await ack.text(), sent: sent?.map((m) => [m.From.Address, m.Subject]), outcome: done?.outcome });
      });

      // 7. The same message delivered again starts nothing.
      await step('7 the same email delivered again starts no run', async () => {
        const before = (await runsOf(ID.mail_intake)).length;
        sendNotice();
        await sleep(8_000);
        const after = (await runsOf(ID.mail_intake)).length;
        check('7 the same email delivered again starts no run', before === 1 && after === 1, { before, after });
      });

      await worker.stop();
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true, tools: { mail: true }, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);

finish();
