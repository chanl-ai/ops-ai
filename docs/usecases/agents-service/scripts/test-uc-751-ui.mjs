// uc-751 Evals keep saved cases and runs for the team, ui layer: docs/usecases/agents-service/evals-keep-saved-cases-and-runs.md.
// Headless Chromium, signed in through platform-service. A builder's saved cases and two runs show on Govern > Evals as
// an admin and as a viewer: three tabs (no Evidence or Judges), counts equal rows, no sample data.
import { AGENTS_PORT, asRole, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const ADMIN = 'p.shah@harborpine.example';
const VIEWER = 'r.menon@harborpine.example';
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
      check('6 no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
