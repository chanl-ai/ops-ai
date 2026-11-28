// uc-792 An admin connects Anthropic and an agent's model settings reach its chat, ui layer: steps 8-14 of
// docs/usecases/models-service/an-admin-connects-anthropic-and-an.md. The run's own demo stack: platform sign-in,
// models-service, agents-service and the fake OpenAI, which stands in for Anthropic's OpenAI-compatible endpoint and
// keeps the settings of each chat request at GET /received. Sam is the account admin (an admin on the Security team);
// James is a builder of Operations.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FAKE_OPENAI_KEY, MODELS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD } from '@ops-ai/usecase-runner/steps';

import { JAMES, as } from '../../lib/workflow_ui.mjs';

const SAM = 's.adeyemi@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const CONNECTION = `anthropic-${TAG}`;
const ALIAS = `fast-${TAG}`;
const MODEL = 'claude-haiku-4-5';
const SHOTS = evidenceDir('792', 'uc-792');
mkdirSync(SHOTS, { recursive: true });
const models = `http://127.0.0.1:${MODELS_PORT}`;
const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const FAKE = `http://127.0.0.1:${process.env.OPS_USECASE_FAKE_OPENAI_PORT ?? 8795}`;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 500));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(read, ok, what, ms = 30_000) {
  const end = Date.now() + ms;
  let last;
  while (Date.now() < end) {
    last = await read();
    if (ok(last)) return last;
    await sleep(500);
  }
  throw new Error(`${what}: ${JSON.stringify(last).slice(0, 300)}`);
}

await withUiStack(
  async (consoleUrl) => {
    const J = await as(JAMES);
    const aliases = (await (await fetch(`${agentsUrl}/v1/model-aliases`, { headers: J })).json()).data;
    const made = await (await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Claims helper ${TAG}`, role: 'Answers claims questions', model: aliases[0].name }) })).json();
    const agentId = made.data.id;
    const everyone = [];

    const browser = await chromium.launch();
    const errors = [];
    try {
      const admin = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      admin.setDefaultTimeout(30_000);

      await step('8 the admin finds Anthropic in the searched list, connects it with its key and sees the key refused for a loopback address', async () => {
        await admin.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByTestId('provider-connections').waitFor({ timeout: 60_000 });
        await admin.getByTestId('provider-connect').click();
        await admin.getByTestId('provider-search').click();
        await admin.getByPlaceholder('Search providers…').last().fill('anthr');
        await admin.getByTestId('provider-search-option-anthropic').click();
        const dialog = admin.getByRole('dialog');
        const fields = await dialog.locator('[data-field]').evaluateAll((els) => els.map((e) => e.getAttribute('data-field')));
        await dialog.getByTestId('provider-connect-name').fill(CONNECTION);
        await dialog.getByTestId('provider-connect-baseUrl').fill(`${FAKE}/v1`);
        await dialog.getByTestId('provider-connect-apiKey').fill(FAKE_OPENAI_KEY);
        const keyType = await dialog.getByTestId('provider-connect-apiKey').getAttribute('type');
        await dialog.getByTestId('provider-connect-save').click();
        await dialog.getByTestId('provider-connect-refused').waitFor();
        await admin.screenshot({ path: join(SHOTS, 'connect-refused.png') });
        check('8 the connect form is the registry\'s (base URL and a masked API key) and the loopback test is refused with the connection saved', fields.join() === 'pc-baseUrl,pc-apiKey' && keyType === 'password', { fields, keyType });
        await dialog.getByTestId('provider-connect-done').click();
        const row = admin.getByTestId('provider-connections').locator('tr', { hasText: CONNECTION });
        await row.waitFor();
        const shown = (await row.innerText()).replace(/\s+/g, ' ');
        everyone.push(await admin.content());
        check('9 the list shows the connection as Anthropic with its endpoint and the key name it signs in with', ['Anthropic', `${FAKE}/v1`, CONNECTION.toUpperCase()].every((t) => shown.includes(t)), shown);
        await row.getByRole('button', { name: 'Open menu' }).click();
        await admin.getByRole('menuitem', { name: 'Models' }).click();
        const sheet = admin.getByTestId('connection-models-sheet');
        await sheet.getByText(MODEL).first().waitFor();
        await admin.screenshot({ path: join(SHOTS, 'models-sheet.png') });
        check('10 the Models sheet lists the catalog\'s Claude models with what each can do', (await sheet.innerText()).includes('Thinking'), (await sheet.innerText()).slice(0, 200));
        await admin.keyboard.press('Escape');
      });

      await step('11 the account admin, not the workspace owner, makes alias fast on the connection, picking the model from its catalog', async () => {
        await admin.goto(`${consoleUrl}/settings/workspace/model-aliases`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByTestId('alias-add').click();
        const dialog = admin.getByRole('dialog');
        await dialog.getByTestId('alias-name').fill(ALIAS);
        await dialog.getByTestId('alias-connection').click();
        await admin.getByPlaceholder('Search connections…').last().fill(CONNECTION);
        await admin.getByRole('option', { name: new RegExp(CONNECTION) }).first().click();
        await dialog.getByTestId('alias-model').click();
        await admin.getByPlaceholder('Search models…').last().fill('haiku');
        await admin.getByTestId(`alias-model-option-${MODEL}`).click();
        await dialog.getByTestId('alias-catalog').waitFor();
        await dialog.getByTestId('alias-cleared').click();
        await admin.getByRole('option', { name: 'Confidential' }).click();
        await admin.screenshot({ path: join(SHOTS, 'alias-dialog.png') });
        await dialog.getByTestId('alias-save').click();
        await dialog.waitFor({ state: 'detached' });
        const row = admin.locator('tr', { hasText: ALIAS });
        await row.waitFor();
        const shown = (await row.innerText()).replace(/\s+/g, ' ');
        check('11 the Aliases list shows the new alias with its connection, model and clearance', [ALIAS, CONNECTION, MODEL, 'Confidential'].every((t) => shown.includes(t)), shown);
      });

      await step('11b on a phone (390 wide) the Aliases and Connections pages fit the screen: no sideways scroll of the page or a table', async () => {
        const wide = admin.viewportSize();
        await admin.setViewportSize({ width: 390, height: 844 });
        const over = {};
        for (const [path, name] of [['model-aliases', ALIAS], ['model-providers', CONNECTION]]) {
          await admin.goto(`${consoleUrl}/settings/workspace/${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.locator('tr', { hasText: name }).first().waitFor({ timeout: 60_000 });
          await admin.screenshot({ path: join(SHOTS, `${path}-390.png`) });
          over[path] = await admin.evaluate(() => [document.scrollingElement, ...document.querySelectorAll('table')].map((e) => (e.tagName === 'TABLE' ? e.scrollWidth - e.parentElement.clientWidth : e.scrollWidth - innerWidth)).filter((d) => d > 1));
        }
        if (wide) await admin.setViewportSize(wide);
        check('11b at 390 neither page nor any of its tables is wider than the screen', Object.values(over).every((d) => d.length === 0), over);
      });

      const builder = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      builder.setDefaultTimeout(30_000);
      const saved = async () => (await (await fetch(`${agentsUrl}/v1/agents/${agentId}`, { headers: J })).json()).data;

      await step('12 the builder picks the alias on the agent and sees only the settings Claude Haiku takes, each at its catalog default', async () => {
        await builder.goto(`${consoleUrl}/build/agents/${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await builder.getByTestId('page-title').first().waitFor({ timeout: 120_000 });
        await builder.getByTestId('agent-model-button').click();
        await builder.locator('#am-alias').click();
        await builder.getByRole('option', { name: ALIAS }).click();
        const form = builder.getByTestId('agent-model-form');
        await form.waitFor();
        const labels = (await form.locator('label').allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim()).sort();
        const defaults = await form.getByText('Default', { exact: true }).count();
        await builder.screenshot({ path: join(SHOTS, 'agent-model-1440.png') });
        check('12 exactly temperature, top p, top k, thinking budget and longest answer show, all on their default', labels.join('|') === ['Longest answer (tokens)', 'Temperature', 'Thinking budget (tokens)', 'Top k', 'Top p'].join('|') && defaults === 5, { labels, defaults });
      });

      await step('13 a setting is changed, reset on its own, and saved with the agent; a number outside the model\'s range keeps the dialog open', async () => {
        await builder.getByTestId('knob-temperature').fill('0.4');
        await builder.getByTestId('knob-top_k').fill('99');
        await builder.getByTestId('knob-top_k-reset').click();
        const afterReset = await builder.getByTestId('knob-top_k').inputValue();
        await builder.getByTestId('knob-top_k').fill('30');
        await builder.getByTestId('knob-thinking_budget').fill('2000');
        await builder.getByTestId('knob-temperature').fill('1.6');
        await builder.getByTestId('agent-model-done').click();
        const stillOpen = await builder.getByTestId('agent-model-form').isVisible();
        const unchanged = JSON.stringify((await saved()).modelSettings ?? {}) === '{}';
        await builder.getByTestId('knob-temperature').fill('0.4');
        await builder.getByTestId('agent-model-done').click();
        const after = await until(saved, (a) => a.model === ALIAS && Object.keys(a.modelSettings ?? {}).length === 3, 'the agent saved its settings');
        await builder.screenshot({ path: join(SHOTS, 'agent-saved-1440.png') });
        check('13 reset empties its field, 1.6 is refused without a save, and 0.4, top k 30 and a 2,000 thinking budget are saved on the alias', afterReset === '' && stillOpen && unchanged && JSON.stringify(after.modelSettings) === JSON.stringify({ temperature: 0.4, top_k: 30, thinking_budget: 2000 }), { afterReset, stillOpen, unchanged, saved: after.modelSettings });
      });

      await step('14 the agent\'s chat reaches the provider with the saved settings', async () => {
        const turn = await fetch(`${agentsUrl}/v1/agents/${agentId}/test`, { method: 'POST', headers: J, body: JSON.stringify({ message: 'Summarise claim CLM-77' }) });
        const received = await (await fetch(`${FAKE}/received`)).json();
        const last = [...received].reverse().find((r) => r.model === MODEL) ?? {};
        check('14 the provider received temperature 0.4, top k 30 and a thinking budget of 2,000', turn.status === 200 && last.temperature === 0.4 && last.top_k === 30 && last.thinking?.type === 'enabled' && last.thinking?.budget_tokens === 2000, { status: turn.status, received: received.slice(-3) });
      });

      await step('15 a builder is offered no Models pages and cannot list or add a connection', async () => {
        await builder.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await builder.getByText('Only an account admin').first().waitFor({ timeout: 60_000 });
        const rail = await builder.getByRole('link', { name: 'Connections', exact: true }).count();
        const listed = await fetch(`${models}/v1/models/providers`, { headers: J });
        // The roles matrix, not an owner rule, refuses the builder an alias write: settings.manage, code admin_only.
        const repoint = await fetch(`${models}/v1/models/aliases/${ALIAS}/versions`, { method: 'POST', headers: { ...J, 'content-type': 'application/json' }, body: JSON.stringify({ providerId: CONNECTION, modelId: MODEL, clearedSensitivity: 'internal' }) });
        const code = (await repoint.json().catch(() => ({})))?.error?.code;
        const body = await builder.content();
        check('15 the page says only an account admin changes models, the rail has no Connections link, the API answers 403, and re-pointing an alias is 403 admin_only', rail === 0 && listed.status === 403 && repoint.status === 403 && code === 'admin_only' && !body.includes(CONNECTION), { rail, status: listed.status, repoint: repoint.status, code });
      });

      const pages = [...everyone, await admin.content(), await builder.content()];
      check('no page shows the provider key', pages.every((p) => !p.includes(FAKE_OPENAI_KEY)));
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
