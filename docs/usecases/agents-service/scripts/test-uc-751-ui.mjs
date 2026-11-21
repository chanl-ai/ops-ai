// uc-751 Evals keep saved cases and runs for the team, ui layer: docs/usecases/agents-service/evals-keep-saved-cases-and-runs.md.
// Headless Chromium, signed in through platform-service. A builder's saved cases and two runs show on Govern > Evals as
// an admin and as a viewer: three tabs (no Evidence or Judges), counts equal rows, no sample data. S6: on the agent's
// Evals tab a builder adds a judge case, runs it and reads the result and its cost; a viewer sees the tab without Add case or Run evals.
// S7: with a failing case run on the newest version, Request publish names the failing step and Publish is disabled; once the case
// is fixed and run again, it is enabled.
import { AGENTS_PORT, asRole, check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const ADMIN = 'p.shah@harborpine.example';
const VIEWER = 'r.menon@harborpine.example';
const BUILDER = 'j.richardson@harborpine.example';
const CASES = {
  cases: [
    { name: 'Greets and offers help', input: 'Hello', checks: [{ type: 'reply_contains', text: 'help' }] },
    { name: 'Looks up the account', input: 'My balance?', checks: [{ type: 'calls_tool', tool: 'lookup_account' }] },
  ],
};

await withUiStack(
  async (consoleUrl) => {
    const builder = await asRole('builder');
    const put = await fetch(`${agents}/v1/agents/ag_branch/eval-cases`, { method: 'PUT', headers: builder, body: JSON.stringify(CASES) });
    const runs = [await fetch(`${agents}/v1/agents/ag_branch/eval-runs`, { method: 'POST', headers: builder }), await fetch(`${agents}/v1/agents/ag_branch/eval-runs`, { method: 'POST', headers: builder })];
    check('1 a builder saves two cases and runs them twice', put.status === 200 && runs.every((r) => r.status === 200), [put.status, ...runs.map((r) => r.status)]);

    const browser = await chromium.launch();
    try {
      const errors = [];
      for (const [who, email] of [['admin', ADMIN], ['viewer', VIEWER]]) {
        const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
        await page.goto(`${consoleUrl}/govern/evals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('suites-row-agent:ag_branch').waitFor({ timeout: 90_000 });
        const tabs = (await page.locator('[data-testid^="assurance-tab-"]').allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
        check(`2 the ${who} sees Suites, Runs and Publish checks, and no Evidence or Judges tab`, tabs.length === 3 && /^Suites/.test(tabs[0]) && /^Runs/.test(tabs[1]) && /^Publish checks/.test(tabs[2]), tabs);
        const suiteRows = await page.locator('tbody tr').count();
        check(`3 the ${who}'s Suites count equals the rows listed`, tabs[0] === `Suites ${suiteRows}`, { tabs: tabs[0], suiteRows });
        await page.getByTestId('assurance-tab-runs').click();
        await page.waitForFunction(() => document.querySelectorAll('tbody tr').length === 2, null, { timeout: 60_000 }).catch(() => undefined);
        const runRows = await page.locator('tbody tr').count();
        check(`4 the ${who}'s Runs tab lists both runs and its count says 2`, runRows === 2 && /Runs 2/.test((await page.getByTestId('assurance-tab-runs').innerText()).replace(/\s+/g, ' ')), runRows);
        const stat = (await page.getByText('Live without a passing run').count()) > 0;
        check(`5 the ${who} reads the renamed stat and no sample-data banner`, stat && (await page.getByText(/sample data/i).count()) === 0, stat);
      }
      // S6: the agent's own Evals tab, on real saved cases and runs.
      const tab = `${consoleUrl}/build/agents/ag_branch?tab=evals`;
      const james = await consoleSignIn(browser, consoleUrl, BUILDER, PASSWORD, errors);
      await james.goto(tab, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('add-eval-case-button').waitFor({ timeout: 90_000 });
      const sample = await james.getByTestId('agent-evals-tab').getByText(/sample|preview/i).allInnerTexts();
      check('16 James reads real cases on the tab: no preview badge or sample text', sample.length === 0, sample);
      await james.getByTestId('add-eval-case-button').click();
      await james.getByLabel('Name').fill('Explains the hold');
      await james.getByLabel('Input').fill('Why is my wire on hold?');
      await james.getByLabel('Check 1 type').click();
      await james.getByRole('option', { name: 'Judge' }).click();
      await james.getByRole('button', { name: 'Add case', exact: true }).last().click();
      check('17 a judge case does not save without its rubric', (await james.getByText('Fill in every check, or remove the empty ones.').count()) === 1, null);
      await james.getByLabel('What a good reply does').fill('Explains in plain words why the wire is held');
      const saved = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/agents/ag_branch/eval-cases'), { timeout: 60_000 });
      await james.getByRole('button', { name: 'Add case', exact: true }).last().click();
      check('18 James saves the judge case', (await saved).status() === 201, null);
      const ran = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/agents/ag_branch/eval-runs'), { timeout: 120_000 });
      await james.getByTestId('run-evals-button').click();
      check('19 James runs the saved cases, three now', (await ran).status() === 200, null);
      await james.getByTestId('eval-run-cost').waitFor({ timeout: 60_000 });
      const cost = (await james.getByTestId('eval-run-cost').innerText()).trim();
      const rate = (await james.getByTestId('eval-run-pass-rate').innerText()).trim();
      check('20 the run shows its pass rate and a cost that includes judging', /^\$\d/.test(cost) && /%|—/.test(rate), { rate, cost });
      await shootBothWidths(james, 'agents-service', 'uc-751-agent-evals-tab', async () => {
        await james.waitForTimeout(300);
      });
      // S7: a failed blocking eval step stops the publish dialog; fixing the case and running again opens it.
      // A new agent is a draft with nothing published, so its header offers Request publish.
      const made = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: builder, body: JSON.stringify({ name: 'Wire hold desk', role: 'Checks wires before they leave' }) })).json()).data;
      const FAILING = { cases: [{ name: 'Never says it', input: 'Hello', checks: [{ type: 'reply_contains', text: 'zzq-never-said-zzq' }] }] };
      const PASSING = { cases: [{ name: 'Replies with words', input: 'Hello', checks: [{ type: 'reply_contains', text: 'could not find' }] }] };
      const rerun = async (set) => {
        const put = await fetch(`${agents}/v1/agents/${made.id}/eval-cases`, { method: 'PUT', headers: builder, body: JSON.stringify(set) });
        const run = await fetch(`${agents}/v1/agents/${made.id}/eval-runs`, { method: 'POST', headers: builder });
        return [put.status, run.status];
      };
      check('22 a failing case is saved and run on the newest version', (await rerun(FAILING)).every((c) => c === 200), null);
      await james.goto(`${consoleUrl}/build/agents/${made.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('request-agent-publish').click({ timeout: 90_000 });
      await james.getByTestId('eval-problem-step-pass_rate').waitFor({ timeout: 60_000 });
      const stepText = (await james.getByTestId('eval-problem-step-pass_rate').innerText()).replace(/\s+/g, ' ');
      check('23 Request publish names the failing pass-rate step and Publish is disabled', /Pass rate/.test(stepText) && (await james.getByTestId('confirm-agent-publish').isDisabled()), stepText);
      check('24 the dialog shows no raw code and links to the Evals tab', (await james.getByTestId('publish-problems').getByText(/eval_failed|cannot_publish/).count()) === 0 && (await james.getByTestId('publish-problem-evals').count()) === 1, null);
      await shootBothWidths(james, 'agents-service', 'uc-751-publish-blocked', async () => {
        await james.waitForTimeout(300);
      });
      await james.keyboard.press('Escape');
      check('25 the fixed case is saved and run again', (await rerun(PASSING)).every((c) => c === 200), null);
      await james.goto(`${consoleUrl}/build/agents/${made.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('request-agent-publish').click({ timeout: 90_000 });
      await james.getByTestId('confirm-agent-publish').waitFor({ timeout: 60_000 });
      await james.waitForTimeout(1500);
      const left = (await james.getByTestId('publish-problems').allInnerTexts()).join(' | ').replace(/\s+/g, ' ');
      check('26 Publish is enabled once the case passes', (await james.getByTestId('eval-problem-steps').count()) === 0 && (await james.getByTestId('confirm-agent-publish').isEnabled()), left);
      const ravi = await consoleSignIn(browser, consoleUrl, VIEWER, PASSWORD, errors);
      await ravi.goto(tab, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await ravi.getByTestId('agent-evals-tab').waitFor({ timeout: 90_000 });
      await ravi.getByTestId('eval-run-summary').waitFor({ timeout: 60_000 });
      check('21 Ravi reads the tab and sees neither Add case nor Run evals', (await ravi.getByTestId('add-eval-case-button').count()) === 0 && (await ravi.getByTestId('run-evals-button').count()) === 0, null);
      check('6 no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
