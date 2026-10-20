// uc-084 an agent finds and runs a workflow whose agent step answers by schema, ui layer (c-062 T005).
// withUiStack's demo stack: ag_advisor holds the seeded v2 customer summary workflow, whose ops.ai.agent step runs
// ag_advisor with the output schema {customerId, summary}; the demo fake-OpenAI rules script both turns. Signed in
// through platform-service as James. UC084_UNGRANTED=1 drops the workflow from ag_advisor's tools first, so search
// finds nothing and the checks must fail. A workflow runner worker takes the run.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const PASSWORD = 'northfield-demo';
const AGENT = 'ag_advisor';
// The demo seed's names (seed/engine_workflows.json); the v2 workflow tool answers with `runId`, which the card links.
const WORKFLOW = 'customer_summary';
const AGENT_NODE = 'summarise';
const ASK = 'Run the customer summary workflow for Priya Natarajan.';
const UNGRANTED = process.env.UC084_UNGRANTED === '1';

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const armed = (p) => (p.catch(() => undefined), p);
// A tool card may re-mount (closed) when the reply finishes, and highlights its input and output after it opens; keep
// it open and read it once the text sought is there, or after 15 s.
const textWhen = async (card, pattern) => {
  const trigger = card.getByRole('button').first();
  let text = '';
  for (let i = 0; i < 30 && !pattern.test(text); i++) {
    if ((await trigger.getAttribute('aria-expanded')) !== 'true') await trigger.click();
    text = await card.innerText();
    if (!pattern.test(text)) await new Promise((r) => setTimeout(r, 500));
  }
  return text;
};

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = as(await tokenFor(JAMES));
    if (UNGRANTED) {
      const agent = (await (await fetch(`${agents}/v1/agents/${AGENT}`, { headers: J })).json()).data;
      const toolIds = (agent?.toolIds ?? []).filter((t) => t !== `workflow:${WORKFLOW}`);
      const res = await fetch(`${agents}/v1/agents/${AGENT}`, { method: 'PATCH', headers: J, body: JSON.stringify({ toolIds }) });
      if (!res.ok) throw new Error(`setup: ungrant answered ${res.status}: ${await res.text()}`);
      // A save is a new version; the live agent changes once it is published.
      const body = JSON.stringify({ version: (await res.json()).data.version, note: 'uc-084 ungrant' });
      const pub = await fetch(`${agents}/v1/agents/${AGENT}/publish-requests`, { method: 'POST', headers: J, body });
      if (!pub.ok) throw new Error(`setup: publish answered ${pub.status}: ${await pub.text()}`);
    }
    const runsOf = async () => (await (await fetch(`${agents}/v1/runs?workflowId=${WORKFLOW}`, { headers: J })).json()).data?.pagination?.total ?? -1;
    const runsBefore = await runsOf();
    const created = await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: AGENT, kbIds: [] }) })).json();
    if (!created.data) throw new Error(`setup: ${JSON.stringify(created).slice(0, 300)}`);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // In the chat: the agent searches its tools, finds the workflow and starts it; the run's outcome comes back.
      await page.goto(`${consoleUrl}/chat/${created.data.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      await box.fill(ASK);
      const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const res = await sent;
      await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 120_000))]);

      const cards = page.getByTestId('chat-tool-call');
      await cards.first().waitFor({ timeout: 60_000 }).catch(() => {});
      const search = cards.filter({ hasText: 'search_tools' });
      // The open search card's result also names the workflow, so the run's card is the one that is not search_tools.
      const run = cards.filter({ hasText: `workflow__${WORKFLOW}` }).filter({ hasNotText: 'search_tools' });
      const searched = (await search.count()) > 0;
      const searchText = searched ? await textWhen(search.first(), new RegExp(`workflow__${WORKFLOW}`)) : '';
      check('the agent searches its tools and the workflow is among the results', searched && searchText.includes(`workflow__${WORKFLOW}`), { searched, cards: await cards.count(), searchText: searchText.slice(0, 400) });

      const ran = (await run.count()) > 0;
      const runText = ran ? await textWhen(run.first(), /customerId[\s\S]*summary|summary[\s\S]*customerId/) : '';
      const state = ran ? await run.first().getAttribute('data-state') : null;
      check('the agent starts the workflow and its outcome comes back with the customer and a summary', ran && state === 'success' && /customerId/.test(runText) && /summary/.test(runText) && /Priya|CUS-/.test(runText), { ran, state, runText: runText.slice(0, 600) });

      // The run, opened from the chat: the agent step's input and output in the journal.
      const open = run.first().getByRole('link', { name: 'Open run' });
      const href = ran ? await open.getAttribute('href', { timeout: 15_000 }).catch(() => null) : null;
      if (href) await open.click();
      const runId = href?.split('/').pop() ?? '';
      const onRun = href ? await page.waitForURL(`**/workflows/runs/${runId}`, { timeout: 60_000 }).then(() => true, () => false) : false;
      const status = onRun ? await page.getByTestId('run-status').innerText({ timeout: 60_000 }).catch(() => '') : '';
      const step = page.locator(`[data-testid="run-step"][data-node-id="${AGENT_NODE}"]`);
      if (onRun) await step.click({ timeout: 60_000 }).catch(() => {});
      const sheet = page.getByTestId('run-step-sheet');
      const sheetText = onRun ? await sheet.innerText({ timeout: 30_000 }).catch(() => '') : '';
      check('the run opens from the chat and shows the agent step with its input and its output by schema', onRun && /succeeded/i.test(status) && /customerId/.test(sheetText) && /summary/.test(sheetText) && /Priya|CUS-/.test(sheetText), { href, onRun, status, sheet: sheetText.slice(0, 600) });

      // Ungranted, the agent never sees the workflow, so the checks above fail by construction; these two show the
      // grant is really gone and that no run started, so the red above is for that reason.
      if (UNGRANTED) {
        const held = (await (await fetch(`${agents}/v1/agents/${AGENT}`, { headers: J })).json()).data?.toolIds ?? null;
        check('ungranted: ag_advisor no longer holds the workflow', Array.isArray(held) && !held.includes(`workflow:${WORKFLOW}`), { held });
        const runsAfter = await runsOf();
        check('ungranted: no run of the workflow started', runsBefore >= 0 && runsAfter === runsBefore, { runsBefore, runsAfter });
      }

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
