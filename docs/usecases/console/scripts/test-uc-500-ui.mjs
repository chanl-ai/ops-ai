// uc-500 A case shows the whole story of its matter and what is left, ui layer: docs/usecases/console/case-story.md
// (c-500). The demo stack (platform sign-in, the fake model's committed answers and reads, the core fake bank, a
// worker). Three kinds of case: a card dispute James starts from its form (Marcus Bell's Coastal Air fare, which waits
// for a credit decision), a tax levy that arrives by test email (TAXLEVY01.pdf, read by the levy mail copies, whose
// case type names its respond-by date and whose read gives the deadline), and a case James opens by hand. Each case page is checked for what is
// left, how it started, its timer and its feed in the example sentences of the spec; screenshots go to
// evidenceDir('500', 'uc').
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const NOTICE = join(ROOT, 'services/documents-service/tests/fixtures/tax_levy/TAXLEVY01.pdf');
const SEED = Object.fromEntries(JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).map((w) => [w.id, w]));
const SHOTS = evidenceDir('500', 'uc');

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 180_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

/** The demo's card dispute and the seeded levy mail workflows under this use case's ids, each starting the next copy. */
function copies(agentId) {
  const dispute = JSON.parse(readFileSync(join(ROOT, 'scripts/demo/workflows/card_dispute_intake.json'), 'utf8').replaceAll('{agent:dispute}', agentId));
  const ids = { levy_mail: 'uc500_mail', levy_read_one: 'uc500_read_one', levy_case: 'uc500_case' };
  const names = { levy_mail: 'Levy mail (uc-500)', levy_read_one: 'Read one levy document (uc-500)', levy_case: 'Levy case (uc-500)' };
  const levy = Object.keys(ids).map((seed) => {
    const { teamId: _team, ...d } = structuredClone(SEED[seed]);
    for (const n of d.nodes) if (n.type === 'ops.action.workflow' && ids[n.parameters.workflow]) n.parameters.workflow = ids[n.parameters.workflow];
    return { ...d, id: ids[seed], name: names[seed] };
  });
  return [{ ...dispute, id: 'uc500_dispute', name: 'Card dispute intake (uc-500)' }, ...levy];
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
    await stack.startWorker({ OPS_FILES_URL: files });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const maya = as(await tokenFor(MAYA));
    const agentId = (await json(await fetch(`${agents}/v1/agents?pageSize=1`, { headers: james })))?.data?.[0]?.id;
    if (!agentId) throw new Error('setup: no agent in Operations');
    for (const definition of copies(agentId)) {
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
          await page.waitForTimeout(800);
          await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`), fullPage: true });
          if (width === 400 && (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth))) errors.push(`${name}: the page scrolls sideways at 400 px`);
        }
        await page.setViewportSize({ width: 1280, height: 900 });
      };
      const run = async (id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers: james }));
      const runsOf = async (wid) => (await json(await fetch(`${agents}/v1/runs?workflowId=${wid}&pageSize=50`, { headers: james }))).data ?? [];
      const caseOf = (r, node) => (r?.steps ?? []).find((s) => s.nodeId === node)?.output?.caseId ?? null;
      /** The case page as a person reads it: the What's left line, how it started, the timer and the feed's lines. */
      const read = async (caseId) => {
        await page.goto(`${consoleUrl}/cases/${caseId}`, { waitUntil: 'domcontentloaded' });
        await page.getByTestId('case-feed').waitFor({ timeout: 60_000 });
        const text = async (id) => ((await page.getByTestId(id).innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
        return { left: await text('case-whats-left'), origin: await text('case-origin'), timer: await text('case-timer'), lines: (await page.getByTestId('case-feed-line').allInnerTexts()).map((t) => t.trim()) };
      };

      let disputeRun = null;
      await step('1 James starts the card dispute from its form', async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
        const picker = page.getByRole('dialog', { name: 'Start a run' });
        await picker.waitFor();
        await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
        await page.getByPlaceholder('Search workflows', { exact: true }).fill('uc-500');
        await page.getByRole('option', { name: /Card dispute intake \(uc-500\)/ }).first().click();
        const form = page.getByRole('dialog', { name: /^Start a run(:| of)/ });
        await form.waitFor();
        await form.getByRole('radio', { name: /Test run/ }).click();
        await form.locator('#run-cardholder').fill('Marcus Bell');
        await form.locator('#run-ssnLast4').fill('4471');
        await form.locator('#run-merchant').fill('Coastal Air');
        await form.locator('#run-amount').fill('1,240.00');
        await form.locator('#run-postedOn').fill('2026-10-16');
        await form.locator('#run-reason').fill('Quoted 640.00 CAD for the flight and charged 1,240.00 CAD; the quote is attached.');
        await form.locator('#run-cardType').click();
        await page.getByRole('option', { name: 'Credit card' }).click();
        const started = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/runs(\/start)?$/.test(r.url()), { timeout: 60_000 });
        await form.getByTestId('definition-start-run-submit').click();
        const res = await started;
        disputeRun = (await res.json()).data?.runId ?? null;
        check('1 James starts the card dispute from its form', res.status() < 300 && !!disputeRun, { status: res.status() });
      });

      let disputeCase = null;
      await step('2 the dispute case says what is left, how it started and what happened', async () => {
        const waiting = await until(async () => {
          const r = await run(disputeRun);
          return r?.waiting && caseOf(r, 'case') ? r : null;
        });
        disputeCase = caseOf(waiting, 'case');
        const seen = await read(disputeCase);
        await shot('dispute-waiting');
        const ok =
          /What's left/.test(seen.left) && /waiting on/i.test(seen.left) && !/Resolve/.test(seen.left) &&
          /James Richardson started Card dispute intake \(uc-500\) from its form/.test(seen.origin) &&
          seen.lines.some((l) => /^Opened a case: (\[Test\] )?Card dispute: Coastal Air/.test(l)) &&
          seen.lines.some((l) => /^Asked .+: /.test(l)) &&
          seen.lines.some((l) => /^James Richardson started Card dispute intake \(uc-500\) from its form$/.test(l)) &&
          !seen.lines.some((l) => /search_customers|list_accounts|_/.test(l.split(':')[0]));
        check('2 the dispute case says what is left, how it started and what happened', ok, seen);
      });

      await step('3 the People filter shows only what people did', async () => {
        await page.getByTestId('case-feed-filter-person').click();
        const shown = await page.locator('[data-testid="case-feed-line"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-source')));
        check('3 the People filter shows only what people did', shown.length > 0 && shown.every((s) => s === 'person'), shown);
      });

      await step('4 once Maya decides and the run ends, nothing is left and Resolve resolves the case', async () => {
        const r = await run(disputeRun);
        const decided = await fetch(`${agents}/reviews/${encodeURIComponent(`${disputeRun}:${r.waiting.node}:${r.waiting.iteration}`)}/decision`, { method: 'POST', headers: maya, body: JSON.stringify({ decision: 'rejected', reason: 'The fare matches the booking class bought.' }) });
        if (decided.status >= 300) throw new Error(`deciding answered ${decided.status} ${(await decided.text()).slice(0, 200)}`);
        await until(async () => ['succeeded', 'failed'].includes((await run(disputeRun))?.status));
        const seen = await read(disputeCase);
        const resolvable = await page.getByTestId('case-resolve').isVisible().catch(() => false);
        await shot('dispute-nothing-left');
        if (resolvable) await page.getByTestId('case-resolve').click();
        const status = await until(async () => /Resolved/.test(await page.getByTestId('case-status-badge').innerText()), 30_000);
        check('4 once Maya decides and the run ends, nothing is left and Resolve resolves the case', /Nothing is left/.test(seen.left) && resolvable && !!status && seen.lines.some((l) => /^Maya Okafor rejected: /.test(l)), { seen, resolvable, status });
      });

      let noticeCase = null;
      await step('5 a tax levy by test email: its case started from the email, timed by the date read from it', async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
        const picker = page.getByRole('dialog', { name: /^Start a run$/ });
        await picker.waitFor();
        await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
        await page.getByPlaceholder('Search workflows', { exact: true }).fill('uc-500');
        await page.getByRole('option', { name: /Levy mail \(uc-500\)/ }).first().click();
        const composer = page.getByRole('dialog', { name: /^Send a test email: Levy mail \(uc-500\)/ });
        await composer.waitFor();
        await composer.getByRole('radio', { name: /Test run/ }).click();
        await composer.locator('#run-from').fill('registry@court.example');
        await composer.locator('#run-subject').fill('Notice of levy SYN-TL-2026-0101');
        await composer.locator('#run-body').fill('Please find the notice of levy attached.');
        await composer.locator('input[type="file"]').first().setInputFiles(NOTICE);
        await composer.getByText(/Uploaded · scan clean|Already stored in your team · reused/).first().waitFor({ timeout: 60_000 });
        await composer.getByTestId('definition-start-run-submit').click();
        noticeCase = await until(async () => {
          for (const r of await runsOf('uc500_read_one')) {
            const id = caseOf(await run(r.id), 'levy_case');
            if (id) return id;
          }
          return null;
        }, 240_000);
        const seen = await read(noticeCase);
        await shot('notice-case');
        const ok =
          /From an email from registry@court\.example: Notice of levy SYN-TL-2026-0101/.test(seen.origin) &&
          /Respond by/.test(seen.timer) &&
          seen.lines.some((l) => /^Email from registry@court\.example: Notice of levy SYN-TL-2026-0101$/.test(l)) &&
          seen.lines.some((l) => /^Read TAXLEVY01\.pdf: /.test(l)) &&
          seen.lines.some((l) => /^Opened a case: (\[Test\] )?Tax levy: Riley Fixture \(SYN-TL-2026-0101\)$/.test(l));
        check('5 a tax levy by test email: its case started from the email, timed by the date read from it', ok, seen);
      });

      await step('6 a case opened by hand says who opened it and offers Resolve', async () => {
        const opened = await json(await fetch(`${agents}/v1/cases`, { method: 'POST', headers: james, body: JSON.stringify({ subject: 'Customer called about a fee (uc-500)', priority: 'normal' }) }));
        const seen = await read(opened.id);
        const resolvable = await page.getByTestId('case-resolve').isVisible().catch(() => false);
        await shot('hand-opened');
        check('6 a case opened by hand says who opened it and offers Resolve', /Opened by James Richardson/.test(seen.origin) && seen.lines.includes('James Richardson opened this case') && /Resolution/.test(seen.timer) && resolvable, { seen, resolvable });
      });

      await step('7 the dispute run page tells what happened in the same sentences', async () => {
        await page.goto(`${consoleUrl}/workflows/runs/${disputeRun}`, { waitUntil: 'domcontentloaded' });
        await page.getByTestId('run-story-feed').waitFor({ timeout: 60_000 });
        const lines = (await page.getByTestId('run-story-feed-line').allInnerTexts()).map((t) => t.trim());
        await shot('dispute-run');
        check('7 the dispute run page tells what happened in the same sentences', lines[0] === 'James Richardson started Card dispute intake (uc-500) from its form' && lines.some((l) => /^Maya Okafor rejected: /.test(l)), lines);
        // The result names who decided and words the decision: a staff address is not customer data, so it never reads [email].
        const result = (await page.getByTestId('run-result').innerText()).replace(/\s+/g, ' ');
        check('7b the result says Rejected by Maya Okafor, not a raw value or a masked address', /Rejected/.test(result) && /Maya Okafor/.test(result) && !/\[email\]|\breject\b/.test(result), result);
      });
      check('8 no page errors and no sideways scroll at 400 px', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
