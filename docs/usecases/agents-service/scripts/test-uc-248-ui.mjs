// uc-248 a hold on a customer's account, ui layer: docs/usecases/agents-service/a-hold-on-a-customer-s.md. The seeded
// customer_hold workflow on the banker demo stack (platform sign-in, tools-service with the core fake bank and its
// webhook stand-in, a worker). Run isolated (ISOLATED=1). No model call. Each check names the steps the run passed.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const SETTLED = ['succeeded', 'failed', 'cancelled'];
const SEED = JSON.parse(execFileSync('cat', [join(ROOT, 'services/agents-service/seed/engine_workflows.json')], { encoding: 'utf8' })).find((w) => w.id === 'customer_hold');

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team = 'team_ops') => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const get = async (url, h) => (await (await fetch(url, { headers: h })).json()).data;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(probe, seconds = 90) {
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

await withUiStack(
  async (consoleUrl, stack) => {
    const J = as(await tokenFor('j.richardson@northfieldbank.com'));
    const P = as(await tokenFor('p.shah@northfieldbank.com'));
    const detail = (id) => get(`${agents}/v1/runs/${id}`, J);
    const start = async (workflowId, input) => (await (await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId, mode: 'live', input }) })).json()).data?.runId;
    const resting = (id) => until(async () => {
      const r = await detail(id);
      return r && (r.status === 'waiting' || SETTLED.includes(r.status)) ? r : undefined;
    });
    const M = as(await tokenFor('m.okafor@northfieldbank.com'));
    // A hold needs two approvals: each person in turn approves while the run still waits at that step.
    const approveEach = async (id, node, people) => {
      const codes = [];
      for (const who of people) {
        const r = await detail(id);
        if ((r?.waiting ?? {}).node !== node) break;
        // Placing a hold asks each approver to re-authenticate first (its approval policy's step-up).
        const stepUp = (await (await fetch(`${agents}/v1/auth/step-up`, { method: 'POST', headers: who, body: JSON.stringify({ password: PASSWORD }) })).json()).data?.token;
        const res = await fetch(`${agents}/reviews/${id}/decision`, { method: 'POST', headers: who, body: JSON.stringify({ decision: 'approved', reason: 'uc-248', stepUpToken: stepUp }) });
        codes.push(res.status === 200 ? 200 : `${res.status} ${(await res.text()).slice(0, 300)}`);
        await sleep(1500);
      }
      return codes;
    };
    const worker = await stack.startWorker({ OPS_ENGINE_POLL_SECONDS: '0.2' });
    await sleep(31_000); // agents-service keeps each tenant's tool list for 30 seconds; the first pass syncs

    // 1. Request, Call a tool (read), Match, Call a tool (read), Set fields, Calculate, If, Human review.
    let held;
    await step('1 the customer is found, matched and their hold worked out, then it waits for approval', async () => {
      held = await resting(await start('customer_hold', { customerName: 'Marcus Bell', ssnLast4: '4471', amount: 2000, reason: 'Garnishment order G-1' }));
      const steps = path(held);
      const calc = held.steps.find((s) => s.nodeId === 'calc')?.output;
      const want = ['start:payload', 'search:ok', 'match:matched', 'accounts:ok', 'facts:out', 'calc:out', 'enough:true'];
      check('1 the customer is found, matched and their hold worked out, then it waits for approval', want.every((s) => steps.includes(s)) && calc?.hold === 2000 && (held.waiting ?? {}).node === 'review', { steps, calc, waiting: held.waiting });
    });

    const browser = await chromium.launch();
    const errors = [];
    try {
      // 2. Human review approved on Human Tasks, Call a tool (write, under the approval), Open case, the webhook, End.
      await step('2 approved on Human Tasks, the hold is placed, a case opens and the outside system is told', async () => {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill('m.okafor@northfieldbank.com');
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByRole('row').filter({ hasText: 'Marcus Bell' }).first();
        await row.waitFor({ timeout: 60_000 });
        await row.click();
        // A held write is a typed write_approval task: it decides by its type's own actions.
        const form = page.getByTestId('option-decision-form');
        await form.waitFor({ timeout: 30_000 });
        const decided = page.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 60_000 });
        await form.getByTestId('decide-approve').click();
        const dialog = page.getByRole('dialog', { name: 'Confirm it is you' });
        await dialog.waitFor({ timeout: 15_000 });
        await page.locator('#reauth-secret').fill(PASSWORD);
        await page.getByTestId('reauth-submit').click();
        const res = await decided.catch(async (e) => {
          throw new Error(`${e}; form: ${(await form.innerText()).slice(0, 400)}`);
        });
        await sleep(1500);
        const second = await approveEach(held.id, 'review', [P]);
        const done = await until(async () => {
          const r = await detail(held.id);
          return SETTLED.includes(r?.status) ? r : undefined;
        });
        const steps = path(done);
        const caseId = done?.steps.find((s) => s.nodeId === 'case')?.output?.caseId;
        const opened = caseId ? await get(`${agents}/v1/cases/${caseId}`, J) : undefined;
        // The stand-in's certificate names the bank's host, so the address is dialled with that name and its CA.
        const read = 'import httpx, ssl, sys; print(httpx.Client(verify=ssl.create_default_context(cafile=sys.argv[2]), timeout=10).send(httpx.Request("GET", sys.argv[1], extensions={"sni_hostname": sys.argv[3]})).text)';
        const hooks = JSON.parse(execFileSync('uv', ['run', '--quiet', 'python', '-c', read, `${stack.bank.url}/webhooks.json`, stack.bank.ca, stack.bank.host], { cwd: join(ROOT, 'services/agents-service'), encoding: 'utf8' }));
        const told = (Array.isArray(hooks) ? hooks : hooks.webhooks ?? []).filter((w) => w.event === 'hold.placed' && w.payload?.caseId === caseId);
        const want = ['review:approve', 'hold:ok', 'case:opened', 'note:added', 'notify:ok'];
        check('2 approved on Human Tasks, the hold is placed, a case opens and the outside system is told', res.status() === 200 && done?.outcome === 'held' && want.every((s) => steps.includes(s)) && opened?.fields?.held === 2000 && !!opened?.fields?.holdId && told.length === 1, { decision: res.status(), second, outcome: done?.outcome, steps, fields: opened?.fields, told: told.length });
      });

      // 6. The editor shows Open case's priority, which takes a fixed choice or a path, as its choice.
      await step('6 the editor shows the case priority as a choice', async () => {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/workflows/definitions/customer_hold`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('[data-testid="definition-node"][data-node-id="case"]').dblclick({ timeout: 60_000 });
        const shown = (await page.locator('[data-field$="-priority"]').first().innerText({ timeout: 30_000 })).trim();
        check('6 the editor shows the case priority as a choice', shown === 'high', { shown });
      });
    } finally {
      await browser.close();
    }

    // 3. Match's none port: a name the bank does not know ends without touching an account.
    await step('3 a customer the bank does not know ends not found', async () => {
      const r = await resting(await start('customer_hold', { customerName: 'Nobody Atall', amount: 50, reason: 'Test' }));
      check('3 a customer the bank does not know ends not found', r?.outcome === 'customer_not_found' && path(r).includes('match:none'), { outcome: r?.outcome, steps: path(r) });
    });

    // 4. If's false port: nothing to hold ends there.
    await step('4 nothing to hold ends at the If', async () => {
      const r = await resting(await start('customer_hold', { customerName: 'Jordan Whitfield', ssnLast4: '5555', amount: 0, reason: 'Test' }));
      check('4 nothing to hold ends at the If', r?.outcome === 'nothing_to_hold' && path(r).includes('enough:false'), { outcome: r?.outcome, steps: path(r) });
    });

    // 5. Human review's deadline: a copy with a deadline of under two seconds expires to the supervisor, who approves the hold.
    await step('5 past the deadline the review times out to a supervisor, who approves the hold', async () => {
      const quick = structuredClone(SEED);
      delete quick.teamId;
      quick.id = 'customer_hold_quick';
      quick.nodes.find((n) => n.id === 'review').parameters.slaHours = 0.0005;
      await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: quick }) });
      const asked = (await (await fetch(`${agents}/v1/workflows/definitions/customer_hold_quick/publish-requests`, { method: 'POST', headers: J, body: '{}' })).json()).data;
      // Publish reviews stay pending on this stack: a second person approves.
      if (asked?.status !== 'approved') {
        const published = await fetch(`${agents}/v1/publish-requests/${asked?.id}/decision`, { method: 'POST', headers: P, body: JSON.stringify({ decision: 'approved' }) });
        if (published.status !== 200) throw new Error(`publish of the quick copy: ${published.status} ${await published.text()}`);
      }
      const id = await start('customer_hold_quick', { customerName: 'Priya Natarajan', ssnLast4: '9032', amount: 300, reason: 'Garnishment order G-2' });
      const atSupervisor = await until(async () => {
        const r = await detail(id);
        return (r?.waiting ?? {}).node === 'supervisor' ? r : undefined;
      }, 120);
      const codes = await approveEach(id, 'supervisor', [P, M]);
      const done = await until(async () => {
        const r = await detail(id);
        return SETTLED.includes(r?.status) ? r : undefined;
      });
      const steps = path(done);
      check('5 past the deadline the review times out to a supervisor, who approves the hold', !!atSupervisor && codes[0] === 200 && done?.outcome === 'held' && ['review:timeout', 'supervisor:approve', 'hold_by_supervisor:ok', 'case:opened', 'note:added'].every((s) => steps.includes(s)), { atSupervisor: !!atSupervisor, decisions: codes, outcome: done?.outcome, steps });
    });

    await worker.stop();
    check('no page errors', errors.length === 0, errors);
  },
  { demo: true },
);

finish();
