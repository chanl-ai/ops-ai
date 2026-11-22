// uc-765 a builder asks two versions of an agent one question and reads the replies side by side, ui layer:
// docs/usecases/console/agent-versions-side-by-side.md. Signed in through platform-service as James; the agents
// service answers on the scripted model. The agent is published as v1 and then edited, so v2 is the newest draft.
import { check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, publishAgent, signInAs } from '@ops-ai/usecase-runner/steps';
import { JAMES } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const QUESTION = 'What is the daily wire limit?';

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const ops = await signInAs(JAMES);
    const { agentId } = await publishAgent(ops, { name: `Wire checker ${TAG}`, role: 'Answers wire questions', instructions: 'Answer in one sentence.' });
    const second = await ops.agents.update(agentId, { instructions: 'Answer in one sentence and name the policy section.' });
    check('0 the agent is published as v1 and edited into v2', second.version === 2, { version: second.version });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const compare = page.getByTestId('agent-compare');
      const sides = page.getByTestId('compare-side');
      const testVersions = [];
      page.on('request', (r) => {
        if (r.method() !== 'POST' || !/\/chat\/threads$/.test(r.url())) return;
        try {
          const body = JSON.parse(r.postData() ?? '{}');
          if (body.test) testVersions.push(body.testVersion ?? 'newest');
        } catch {
          // a body that is not JSON is not a thread
        }
      });

      await step('1 Compare opened by its address offers v2 against the published v1', async () => {
        await page.goto(`${consoleUrl}/build/agents/${agentId}/versions/compare`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await compare.waitFor({ timeout: 120_000 });
        await page.waitForTimeout(1500);
        const picked = (await page.getByTestId('compare-version').innerText()).trim();
        const placeholder = await page.locator('textarea').last().getAttribute('placeholder');
        check('1 Compare opened by its address offers v2 against the published v1', /^v1 \(published\)$/.test(picked) && placeholder === 'Ask v2 and v1…', { picked, placeholder });
      });

      await step('2 from the Versions tab Compare says to ask both, and one question draws two sides with a reply each', async () => {
        await page.goto(`${consoleUrl}/build/agents/${agentId}/versions`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('agent-compare-link').click({ timeout: 120_000 });
        await compare.waitFor({ timeout: 60_000 });
        const picked = (await page.getByTestId('compare-version').innerText()).trim();
        const empty = await page.getByText('Ask both versions').count();
        check('2a Compare from the Versions tab offers v2 against the published v1 and asks to ask both', /^v1 \(published\)$/.test(picked) && empty === 1 && (await sides.count()) === 0, { picked, empty });
        const box = page.getByPlaceholder(/^Ask v2 and v1/);
        await box.fill(QUESTION);
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        await sides.nth(1).waitFor({ timeout: 60_000 });
        await page.getByText('Thinking…').first().waitFor({ state: 'hidden', timeout: 60_000 }).catch(() => undefined);
        await page.waitForTimeout(1000);
        const labels = await sides.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
        const texts = await sides.allInnerTexts();
        const asked = texts.filter((t) => t.includes(QUESTION)).length;
        const replied = texts.filter((t) => t.replace(QUESTION, '').replace(/v\d+( \(newest\))?/, '').trim().length > 20).length;
        await shootBothWidths(page, 'console', 'uc-765-side-by-side', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('2b one question draws two sides, one per version, each with a reply', JSON.stringify(labels) === JSON.stringify(['v2 (newest)', 'v1']) && asked === 2 && replied === 2, { labels, asked, replied, texts: texts.map((t) => t.slice(0, 120)) });
      });

      await step('3 each side ran on its own version of the agent', async () => {
        check('3 each side ran on its own version of the agent', testVersions.length === 2 && testVersions.includes('newest') && testVersions.includes(1), { testVersions });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
