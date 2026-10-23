// uc-508 Steps read in sentences everywhere a person reads them, ui layer: docs/usecases/console/steps-in-sentences.md
// (c-508). The demo stack (platform sign-in, the core fake bank, a worker). James starts a copy of the seeded hold
// workflow for Marcus Bell; Activity, Maya's Human Task, the case the run opens and the run page are each checked for
// what a person reads: sentences, the operation's labels, a first response once a person works the case, the outcome in
// words and the workflow by its name. Screenshots go to evidenceDir('508', 'uc').
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const WORKFLOW = 'uc508_hold';
const NAME = "Hold on a customer's account (uc-508)";
const SEED = JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).find((w) => w.id === 'customer_hold');
const SHOTS = evidenceDir('508', 'uc');
// A step's own name where a person reads: an operation, a node id or an input key.
const NAMES = /\b(search_customers|list_accounts|place_hold|add_to_case|notify_webhook|account_id|accountId|customer_id|uc508_hold)\b/;

const tokenFor = async (email) =>
  (
    await (
      await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })
    ).json()
  ).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 180_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const mayaToken = await tokenFor(MAYA);
    const maya = as(mayaToken);
    const { teamId: _team, ...definition } = structuredClone(SEED);
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ definition: { ...definition, id: WORKFLOW, name: NAME } }) });
    if (saved.status >= 300) throw new Error(`setup: saving ${WORKFLOW} answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
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

      let runId = null;
      let waiting = null;
      await step('1 James starts a hold on Marcus Bell and it waits on a Human Task', async () => {
        const input = { customerName: 'Marcus Bell', ssnLast4: '4471', amount: 2140.55, reason: 'Levy SYN-TL-2026-0101' };
        const started = await fetch(`${agents}/v1/runs`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: WORKFLOW, mode: 'test', input }) });
        runId = (await json(started))?.runId ?? null;
        waiting = await until(async () => {
          const r = runId && (await run(runId));
          return r?.waiting ? r : null;
        });
        check('1 James starts a hold on Marcus Bell and it waits on a Human Task', started.status < 300 && !!waiting, { status: started.status, runId, state: waiting?.status });
      });

      await step("2 Activity reads the run's calls as sentences", async () => {
        await page.goto(`${consoleUrl}/activity?source=workflow:${WORKFLOW}`, { waitUntil: 'domcontentloaded' });
        const rows = page.locator('[data-testid^="activity-row-"]');
        await rows.first().waitFor({ timeout: 60_000 });
        const titles = await rows.evaluateAll((els) => els.map((e) => (e.querySelector('td span span')?.textContent ?? '').trim()));
        await shot('activity');
        const calls = titles.filter((t) => /^(Search customers|List accounts)\b/.test(t));
        check("2 Activity reads the run's calls as sentences", calls.length >= 2 && !titles.some((t) => NAMES.test(t)), titles);
      });

      const reviewId = waiting ? `${runId}:${waiting.waiting.node}:${waiting.waiting.iteration}` : '';
      await step("3 Maya's Human Task says what the hold changes in the operation's words", async () => {
        const mayaPage = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
        try {
          const task = await json(await fetch(`${agents}/reviews/${encodeURIComponent(reviewId)}`, { headers: maya }));
          const preview = (task?.task?.regions ?? []).find((r) => r.region === 'write_preview')?.data ?? {};
          await mayaPage.goto(`${consoleUrl}/reviews/${encodeURIComponent(reviewId)}`, { waitUntil: 'domcontentloaded' });
          await mayaPage.getByTestId('task-body').waitFor({ timeout: 60_000 });
          const body = (await mayaPage.getByTestId('task-body').innerText()).replace(/\s+/g, ' ');
          await mayaPage.screenshot({ path: join(SHOTS, 'human-task-1280.png'), fullPage: true });
          const labels = (preview.fields ?? []).map((f) => f.label);
          check(
            "3 Maya's Human Task says what the hold changes in the operation's words",
            labels.length > 0 && !!preview.sentence && !labels.some((l) => NAMES.test(l) || l.includes('_')) && !NAMES.test(body),
            { labels, sentence: preview.sentence, body: body.slice(0, 600) },
          );
        } finally {
          await mayaPage.context().close();
        }
      });

      let caseId = null;
      await step('4 the case the run opens has no first response until a person works it', async () => {
        // A hold moves money, so its approval asks Maya to re-enter her password first.
        const stepUpToken = (
          await json(
            await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/step-up`, {
              method: 'POST',
              headers: { Authorization: `Bearer ${mayaToken}`, 'Content-Type': 'application/json' },
              body: JSON.stringify({ password: PASSWORD }),
            }),
          )
        )?.token;
        const decided = await fetch(`${agents}/reviews/${encodeURIComponent(reviewId)}/decision`, {
          method: 'POST',
          headers: maya,
          body: JSON.stringify({ decision: 'approved', reason: 'The levy names this account.', stepUpToken }),
        });
        if (decided.status >= 300) throw new Error(`deciding answered ${decided.status} ${(await decided.text()).slice(0, 200)}`);
        const done = await until(async () => {
          const r = await run(runId);
          return ['succeeded', 'failed'].includes(r?.status) ? r : null;
        });
        caseId = (done?.steps ?? []).find((s) => s.nodeId === 'case')?.output?.caseId ?? null;
        const before = await json(await fetch(`${agents}/v1/cases/${caseId}`, { headers: james }));
        const noted = await fetch(`${agents}/v1/cases/${caseId}/events`, { method: 'POST', headers: james, body: JSON.stringify({ kind: 'note', text: 'Called the customer about the hold.' }) });
        await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded' });
        // First response is one of the columns the table hides until a person shows it from View.
        await page.getByRole('button', { name: 'View' }).click();
        await page.getByRole('menuitemcheckbox', { name: /response/i }).click();
        await page.keyboard.press('Escape');
        await shot('cases');
        const cell = page.locator('tr', { hasText: "Marcus Bell's account" }).getByTestId('case-response').first();
        await cell.waitFor({ timeout: 30_000 });
        const state = await cell.getAttribute('data-state');
        check('4 the case the run opens has no first response until a person works it', done?.status === 'succeeded' && !!caseId && !before?.respondedAt && noted.status < 300 && state === 'met', {
          status: done?.status,
          caseId,
          before: before?.respondedAt,
          noted: noted.status,
          state,
        });
      });

      await step('5 the run page names the workflow and says the outcome in words', async () => {
        await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded' });
        const panel = page.getByTestId('run-attributes');
        await panel.waitFor({ timeout: 60_000 });
        await page.getByTestId('run-story-feed').waitFor({ timeout: 60_000 });
        const text = (await panel.innerText()).replace(/\s+/g, ' ');
        const lines = (await page.getByTestId('run-story-feed-line').allInnerTexts()).map((t) => t.trim());
        await shot('run');
        check(
          '5 the run page names the workflow and says the outcome in words',
          text.includes('Held') &&
            text.includes(`${NAME} v`) &&
            !/uc508_hold v/.test(text) &&
            lines.some((l) => /^Maya Okafor approved: Hold 2,140\.55 on Marcus Bell$/.test(l)) &&
            !lines.some((l) => NAMES.test(l)),
          { text, lines },
        );
      });
      check('6 no page errors and no sideways scroll at 400 px', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
