// uc-246 a mixed levy email is read by kind, ui layer: docs/usecases/agents-service/a-mixed-levy-email-is-read.md (the
// levy demo, 2026-10-18 plan). withUiStack on the banker demo: platform sign-in, models on the fake OpenAI with the
// demo's committed rules (which replay the shared stack's real classifications and reads of these files), tools-service
// with the core fake bank and its webhook stand-in, GreenMail and Mailpit reachable (tools.mail), the seeded mailboxes,
// and a worker. Run isolated (ISOLATED=1). Real mail both ways; nothing else faked but the bank and the model.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const MAILPIT = `http://127.0.0.1:${process.env.OPS_MAILPIT_HTTP_PORT ?? 8025}`;
const GREENMAIL_SMTP = process.env.OPS_GREENMAIL_SMTP_PORT ?? '3025';
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
// The reply goes out through send_reply on the Messaging Platform team's mail module, so that team approves the write.
const WANJIRU = 'w.kamau@harborpine.example';
const MAILBOX = 'levies@harborpine.test';
const SENDER = 'service@process.example';
const SETTLED = ['succeeded', 'failed', 'cancelled'];
// Worker-x's mixed levy email (two restraining notices and a tax levy) plus a second tax levy whose taxpayer the model
// quotes from words not on the page. Two reads wait on a person: that one, and TEST012, whose committed fake read
// leaves fields the page does not support.
const DOUBTFUL = ['TEST012.pdf', 'TAXLEVY02.pdf'];
const EXPECTED = {
  'TEST006.pdf': { outcome: 'restraining_notice', subject: 'Restraining notice: Parker Demo (SYN-2026-0006)' },
  'TEST012.pdf': { outcome: 'restraining_notice', subject: 'Restraining notice: Sage Prototype (SYN-2026-0012)' },
  'TAXLEVY01.pdf': { outcome: 'tax_levy', subject: 'Tax levy: Riley Fixture (SYN-TL-2026-0101)' },
  'TAXLEVY02.pdf': { outcome: 'tax_levy', subject: 'Tax levy:' },
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

function sendLevies() {
  const script = `
import base64, json, smtplib, sys
sys.path.insert(0, "scripts")
from send_levy_email import message
item = json.load(open("../documents-service/tests/fixtures/mail/mixed_levies.json"))
extra = open("../documents-service/tests/fixtures/tax_levy/TAXLEVY02.pdf", "rb").read()
item["attachments"].append({"name": "TAXLEVY02.pdf", "contentType": "application/pdf", "contentBytes": base64.b64encode(extra).decode()})
with smtplib.SMTP("127.0.0.1", int(sys.argv[2])) as s:
    s.send_message(message(item, sys.argv[1]))
`;
  execFileSync('uv', ['run', '--quiet', 'python', '-c', script, MAILBOX, GREENMAIL_SMTP], { cwd: join(ROOT, 'services/agents-service'), stdio: 'pipe' });
}

await withUiStack(
  async (consoleUrl, stack) => {
    const S = as(await tokenFor(SAM), 'team_security');
    const J = as(await tokenFor(JAMES));
    const W = as(await tokenFor(WANJIRU), 'team_platform');
    const runsOf = async (workflow) => (await get(`${agents}/v1/runs?workflowId=${workflow}&pageSize=50`, J))?.data ?? [];
    const detail = (id) => get(`${agents}/v1/runs/${id}`, J);
    const stepOf = (run, node) => (run?.steps ?? []).find((s) => s.nodeId === node);

    // 0. A Security admin puts the seeded mailboxes' password on the Secrets page and allows the mail hosts.
    await step('0 Sam stores the mailbox secret and allows the mail hosts', async () => {
      const secret = await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: 'DEV_IMAP_PASSWORD', value: 'any', teamId: 'team_ops' }) });
      const allowed = [];
      for (const value of [stack.mail.imapHost, stack.mail.smtpHost]) allowed.push((await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value, note: 'uc-246' }) })).status);
      allowed.push((await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.mail.range, note: 'uc-246' }) })).status);
      check('0 Sam stores the mailbox secret and allows the mail hosts', secret.status === 201 && allowed.every((s) => s === 201 || s === 200), { secret: secret.status, allowed });
    });

    const worker = await stack.startWorker({ OPS_EMAIL_POLL_SECONDS: '1', OPS_ENGINE_POLL_SECONDS: '0.2' });
    await sleep(31_000); // agents-service keeps each tenant's tool list for 30 seconds; the first pass syncs

    // 1. The email arrives; one levy_mail run starts a levy_read_one run per attachment.
    let parent;
    let children = [];
    await step('1 the email starts one run that reads each attachment in its own run', async () => {
      sendLevies();
      parent = await until(async () => (await runsOf('levy_mail')).find((r) => r.status === 'waiting' || SETTLED.includes(r.status)));
      children = (await until(async () => {
        const kids = (await runsOf('levy_read_one')).filter((k) => k.startedBy?.runId === parent?.id);
        return kids.length === 4 && kids.every((k) => k.status === 'waiting' || SETTLED.includes(k.status)) ? kids : undefined;
      }, 180)) ?? [];
      const names = children.map((k) => k.input?.name).sort();
      check('1 the email starts one run that reads each attachment in its own run', parent?.status === 'waiting' && JSON.stringify(names) === JSON.stringify(Object.keys(EXPECTED).sort()), { parent: parent?.status, names });
    });

    // 2. The children ran together: from the first read's start to the last one's end took less time than the reads
    // take one after another, which a worker running them in turn cannot do.
    await step('2 the documents are read in parallel', async () => {
      const reads = [];
      for (const k of children) {
        const attempt = stepOf(await detail(k.id), 'read')?.attempts?.at(-1);
        if (attempt) reads.push([Date.parse(attempt.startedAt), Date.parse(attempt.finishedAt)]);
      }
      const span = Math.max(...reads.map(([, e]) => e)) - Math.min(...reads.map(([s]) => s));
      const inTurn = reads.reduce((sum, [s, e]) => sum + (e - s), 0);
      check('2 the documents are read in parallel', reads.length === 4 && span < inTurn, { span, inTurn, reads });
    });

    // 3. Each kind is detected and routed; the doubtful reads wait on Check the read.
    await step('3 each kind is detected and the doubtful reads wait for a person', async () => {
      const done = children.filter((k) => !DOUBTFUL.includes(k.input?.name)).map((k) => [k.input.name, k.outcome]);
      const waiting = children.filter((k) => DOUBTFUL.includes(k.input?.name)).map((k) => (k.waiting ?? {}).node);
      check('3 each kind is detected and the doubtful reads wait for a person', done.length === 2 && done.every(([n, o]) => EXPECTED[n].outcome === o) && waiting.join() === 'check,check', { done, waiting });
    });

    const browser = await chromium.launch();
    const errors = [];
    try {
      // 4. Maya checks each doubtful read on Human Tasks and approves it; their cases open.
      await step('4 Maya approves the doubtful reads on Human Tasks and their cases open', async () => {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(MAYA);
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        const decisions = [];
        for (const name of DOUBTFUL) {
          await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const row = page.getByRole('row').filter({ hasText: name }).first();
          await row.waitFor({ timeout: 60_000 });
          await row.click();
          const form = page.getByTestId('review-decision-form');
          await form.waitFor({ timeout: 30_000 });
          const decided = page.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 60_000 });
          await form.getByRole('button', { name: 'Approve', exact: true }).click();
          decisions.push((await decided).status());
        }
        const outcomes = [];
        for (const name of DOUBTFUL) {
          const kid = children.find((k) => k.input?.name === name);
          const after = await until(async () => {
            const r = await detail(kid.id);
            return SETTLED.includes(r?.status) ? r : undefined;
          });
          outcomes.push(after?.outcome);
        }
        check('4 Maya approves the doubtful reads on Human Tasks and their cases open', decisions.join() === '200,200' && outcomes.join() === 'restraining_notice,tax_levy', { decisions, outcomes });
      });
    } finally {
      await browser.close();
    }

    // 5. One case per document, named from what was read; the tax levy's terms are worked out by Calculate.
    let caseIds = [];
    await step('5 a case per document, and the tax levy terms worked out', async () => {
      const opened = [];
      let terms;
      let kept;
      for (const k of children) {
        const run = await detail(k.id);
        const id = (stepOf(run, 'notice_case') ?? stepOf(run, 'levy_case'))?.output?.caseId;
        const found = id ? await get(`${agents}/v1/cases/${id}`, J) : undefined;
        opened.push([k.input.name, found?.subject]);
        if (id) caseIds.push(id);
        if (k.input.name === 'TAXLEVY01.pdf') {
          terms = stepOf(run, 'levy_terms')?.output;
          kept = found?.fields;
        }
      }
      const named = opened.every(([n, subject]) => subject?.startsWith(EXPECTED[n].subject));
      // The case keeps what was read and worked out, so a person sees it without opening the run.
      const keeps = kept?.taxpayer === 'Riley Fixture' && kept?.amountDue === 7482.19 && kept?.respondBy === '2026-10-27';
      check('5 a case per document, and the tax levy terms worked out', named && terms?.amount === 7482.19 && terms?.days_to_respond === 21 && keeps, { opened, terms, kept });
    });

    // 6. The outside system received one levy.processed payload per document, through the tools gateway.
    await step('6 the webhook stand-in received one payload per document', async () => {
      // The stand-in's certificate names the bank's host, so the address is dialled with that name and its CA.
      const read = 'import httpx, ssl, sys; print(httpx.Client(verify=ssl.create_default_context(cafile=sys.argv[2]), timeout=10).send(httpx.Request("GET", sys.argv[1], extensions={"sni_hostname": sys.argv[3]})).text)';
      const raw = JSON.parse(execFileSync('uv', ['run', '--quiet', 'python', '-c', read, `${stack.bank.url}/webhooks.json`, stack.bank.ca, stack.bank.host], { cwd: join(ROOT, 'services/agents-service'), encoding: 'utf8' }));
      const got = (Array.isArray(raw) ? raw : raw.webhooks ?? []).filter((w) => w.event === 'levy.processed' && caseIds.includes(w.payload?.caseId));
      check('6 the webhook stand-in received one payload per document', got.length === 4, { received: got.map((w) => [w.payload?.document, w.payload?.caseId]) });
    });

    // 7. The mail module's team acknowledges; the reply leaves from the levies mailbox and lands in Mailpit.
    await step('7 the acknowledgement sends one reply from the levies mailbox', async () => {
      const replies = async () => {
        const found = await (await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${SENDER}"`)}`)).json();
        return (found.messages ?? []).filter((m) => m.From.Address === MAILBOX).length;
      };
      const before = await replies(); // an earlier run on this Mailpit may have replied to the same sender
      const ack = await fetch(`${agents}/reviews/${parent.id}/decision`, { method: 'POST', headers: W, body: JSON.stringify({ decision: 'approved', reason: 'uc-246' }) });
      const done = await until(async () => {
        const r = await detail(parent.id);
        return SETTLED.includes(r?.status) ? r : undefined;
      }, 60);
      const after = await until(async () => ((await replies()) > before ? await replies() : undefined), 60);
      check('7 the acknowledgement sends one reply from the levies mailbox', ack.status === 200 && done?.outcome === 'replied' && after === before + 1, { ack: ack.status === 200 ? 200 : await ack.text(), outcome: done?.outcome, before, after });
    });

    await worker.stop();
    check('no page errors', errors.length === 0, errors);
  },
  { demo: true, tools: { mail: true }, agentsEnv: { OPS_MAILBOXES_SEED_FILE: 'seed/mailboxes.json' } },
);

finish();
