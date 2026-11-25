// uc-764 an agent page saves itself and holds its model, knowledge, tools and skills on the main page, ui layer:
// docs/usecases/console/agent-page-settings-and-channels.md. Demo stack signed in through platform-service as James:
// its knowledge bases and tools are the ones the pickers search. A published agent and a draft agent show the
// Channels tab differently.
import { AGENTS_PORT, check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, publishAgent, signInAs } from '@ops-ai/usecase-runner/steps';
import { JAMES, agents, as } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);

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
    const J = await as(JAMES);
    const get = async (path) => (await (await fetch(`${agents}${path}`, { headers: J })).json()).data;
    const { agentId } = await publishAgent(ops, { name: `Desk ${TAG}`, role: 'Answers desk questions', instructions: 'Answer in one sentence.' });
    const draft = await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Draft desk ${TAG}`, role: 'Not published yet' }) })).json();
    const skill = (await (await fetch(`${agents}/v1/skills`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Desk steps ${TAG}`, ownerTeam: 'team_ops', useWhen: 'A desk question needs steps.', instructions: 'Say what each step found.', steps: [{ do: 'Ask what the person needs.' }] }) })).json()).data;
    await fetch(`${agents}/v1/skills/${skill.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'use case' }) });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      page.setDefaultTimeout(30_000);
      const writes = [];
      page.on('request', (r) => r.method() !== 'GET' && r.url().includes(`:${AGENTS_PORT}/`) && writes.push(`${r.method()} ${new URL(r.url()).pathname} ${(r.postData() ?? '').slice(0, 120)}`));
      const state = () => page.getByTestId('save-state').first();
      const open = async (id, tab = '') => {
        await page.goto(`${consoleUrl}/build/agents/${id}${tab}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('page-title').first().waitFor({ timeout: 120_000 });
      };
      const pick = async (testId, search) => {
        await page.locator('[data-testid="save-state"][data-state="saved"]').first().waitFor({ timeout: 30_000 });
        await page.getByTestId(testId).getByRole('button', { name: 'Add', exact: true }).click();
        if (search) await page.getByPlaceholder(/^Search/).last().fill(search);
        const option = page.locator('[role=option]:not([aria-disabled=true]):not([data-disabled=true])').first();
        await option.waitFor({ timeout: 30_000 });
        const label = (await option.innerText()).split('\n')[0];
        await option.click();
        await page.keyboard.press('Escape');
        return label;
      };

      await step('1 the header says Saved, and the model, knowledge, tools and skills are on the main page', async () => {
        await open(agentId);
        await state().waitFor();
        const has = {
          saved: await state().getAttribute('data-state'),
          model: await page.locator('#ag-model').count(),
          knowledge: await page.getByTestId('agent-knowledge-picker').count(),
          tools: await page.getByTestId('agent-tools-picker').count(),
          skills: await page.getByTestId('agent-skills-section').count(),
        };
        await shootBothWidths(page, 'console', 'uc-764-agent-page', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('1 the header says Saved, and the model, knowledge, tools and skills are on the main page', has.saved === 'saved' && has.model === 1 && has.knowledge === 1 && has.tools === 1 && has.skills === 1, has);
      });

      await step('2 a change goes Unsaved, Saving, Saved by itself and reaches the agent', async () => {
        await page.evaluate(() => {
          window.__states = [];
          const el = document.querySelector('[data-testid="save-state"]');
          new MutationObserver(() => window.__states.push(el.getAttribute('data-state'))).observe(el, { attributes: true, attributeFilter: ['data-state'] });
        });
        await page.getByLabel('Agent name').fill(`Desk ${TAG} renamed`);
        await page.locator('[data-testid="save-state"][data-state="saved"]').waitFor({ timeout: 30_000 });
        await page.waitForTimeout(500);
        const seen = await page.evaluate(() => window.__states);
        const stored = await get(`/v1/agents/${agentId}`);
        check('2 a change goes Unsaved, Saving, Saved by itself and reaches the agent', seen.includes('unsaved') && seen.at(-1) === 'saved' && stored.name === `Desk ${TAG} renamed`, { seen, name: stored.name });
      });

      await step('3 a knowledge base picked on the page is added to the agent', async () => {
        await page.locator('[data-testid="save-state"][data-state="saved"]').first().waitFor({ timeout: 30_000 });
        await page.getByTestId('agent-knowledge-picker').getByRole('button', { name: 'Add', exact: true }).click();
        const option = page.getByRole('option').first();
        await option.waitFor({ timeout: 30_000 });
        const label = (await option.innerText()).split('\n')[0];
        const before = writes.length;
        await option.click();
        await page.waitForTimeout(2000);
        const byClick = writes.length > before;
        let byKey = false;
        if (!byClick) {
          await page.keyboard.press('Enter');
          await page.waitForTimeout(2000);
          byKey = writes.length > before;
        }
        await page.keyboard.press('Escape');
        const stored = await get(`/v1/agents/${agentId}`);
        check('3 a knowledge base picked on the page is added to the agent', stored.collections.length === 1, { label, byClick, byKey, collections: stored.collections, writes: writes.slice(before) });
      });

      await step('4 a tool picked on the page is granted to the agent', async () => {
        const label = await pick('agent-tools-picker');
        await page.waitForTimeout(1500);
        const stored = await get(`/v1/agents/${agentId}`);
        check('4 a tool picked on the page is granted to the agent', stored.toolIds.length === 1 && (await page.getByText(label, { exact: false }).count()) > 0, { label, toolIds: stored.toolIds });
      });

      await step('5 a published skill attached on the page is pinned to the agent', async () => {
        await page.getByTestId('attach-skill-button').getByRole('button').first().click().catch(() => page.getByTestId('attach-skill-button').click());
        await page.getByPlaceholder('Search skills…').fill(`Desk steps ${TAG}`);
        await page.getByRole('option', { name: new RegExp(`Desk steps ${TAG}`) }).first().click();
        await page.getByTestId('agent-skill-pins').waitFor({ timeout: 30_000 });
        const pins = await page.getByTestId('agent-skill-pins').innerText();
        check('5 a published skill attached on the page is pinned to the agent', pins.includes(`Desk steps ${TAG}`), pins);
      });

      await step('6 Channels shows the ways to reach a published agent', async () => {
        await page.getByTestId('agent-channels-tab-trigger').click();
        await page.getByText('Ways to reach it').waitFor({ timeout: 30_000 });
        const seen = { url: new URL(page.url()).pathname, chat: await page.getByText('Chat', { exact: true }).count(), api: await page.getByText('API and SDK').count(), embed: await page.getByText('Embed on a page').count() };
        await shootBothWidths(page, 'console', 'uc-764-agent-channels', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('6 Channels shows the ways to reach a published agent', /\/channels$/.test(seen.url) && seen.chat > 0 && seen.api > 0 && seen.embed > 0, seen);
      });

      await step('7 a draft agent says to publish it before it is in channels', async () => {
        await open(draft.data.id, '/channels');
        const empty = await page.getByText('Publish the agent to put it in channels').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check('7 a draft agent says to publish it before it is in channels', empty && (await page.getByText('Ways to reach it').count()) === 0, { empty });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
