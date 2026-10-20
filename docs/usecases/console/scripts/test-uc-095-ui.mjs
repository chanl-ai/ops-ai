// uc-095 an agent fills a pinned widget and lays out its own in chat, ui layer:
// docs/usecases/console/agent-fills-widgets.md. Scripted model only; signed in through platform-service.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const armed = (p) => (p.catch(() => undefined), p);

const HOLD = { holdId: 'hold_204', payee: 'Acme Supplies Ltd', amount: 12500, currency: 'USD', status: 'held', reason: 'First payment to a new payee', account: 'CHQ-2219' };
const COMPOSED = { type: 'card', title: 'Two holds are open', children: [{ type: 'keyValue', items: [{ label: 'Total held', value: 'USD 18,250.00' }] }] };

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const agent = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Holds desk ${TAG}`, role: 'Explains payment holds' }) }));
    const offered = (await json(await fetch(`${agentsUrl}/v1/tools`, { headers: J }))).map((t) => t.id ?? t.name);
    check('the tool Hold review needs is in the directory', offered.includes('lookup_account'), offered);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // Step 1: the agent page's Widgets section. Hold review's button (the scripted stack's fixture library) asks for
      // lookup_account, which this agent does not hold yet, so the widget cannot be chosen until the tool is granted.
      await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // The widget picker (EntityPicker, c-136) offers Hold review disabled, naming the tool it needs.
      await page.getByTestId('agent-widget-pins').getByRole('button', { name: 'Choose widgets' }).click({ timeout: 120_000 });
      await page.getByPlaceholder('Search widgets…').fill('Hold review');
      const option = page.getByRole('option', { name: /Hold review/ });
      await option.waitFor({ timeout: 30_000 });
      const blocked = (await option.getAttribute('aria-disabled')) === 'true' && (await option.innerText()).includes('Needs lookup_account');
      check('Hold review cannot be chosen while the agent lacks the tool its button needs', blocked);
      await page.keyboard.press('Escape');
      const granted = await fetch(`${agentsUrl}/v1/agents/${agent.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ toolIds: ['lookup_account'] }) });
      if (!granted.ok) throw new Error(`setup: granting lookup_account answered ${granted.status}: ${await granted.text()}`);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('agent-widget-pins').getByRole('button', { name: 'Choose widgets' }).click({ timeout: 120_000 });
      await page.getByPlaceholder('Search widgets…').fill('Hold review');
      await page.getByRole('option', { name: /Hold review/ }).click({ timeout: 30_000 });
      await page.keyboard.press('Escape');
      await page.getByTestId('agent-widget-pins').getByText('Hold review').waitFor({ timeout: 15_000 }).catch(() => undefined);
      await page.getByRole('switch', { name: 'Lay out its own widgets' }).click();
      const pinned = (await page.getByTestId('agent-widget-pins').innerText()).includes('Hold review');
      check('the agent page pins Hold review and switches composing on', pinned, { pinned });
      const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/agents/${agent.id}`), { timeout: 60_000 }));
      await page.getByRole('button', { name: /^Save/ }).first().click();
      const dialog = page.getByRole('dialog');
      if (await dialog.isVisible().catch(() => false)) await dialog.getByRole('button', { name: /^Save/ }).last().click();
      const res = await saved;
      const body = res ? await res.json() : {};
      check('the saved version holds the widget pin and composing', body.data?.widgetPins?.[0]?.widgetId === 'hold-review' && body.data?.widgets?.compose === true, { pins: body.data?.widgetPins, widgets: body.data?.widgets });
      await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: body.data.version, note: 'uc-095' }) }));

      const thread = (await json(await fetch(`${agentsUrl}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) }))).id;
      await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      const send = async (text) => {
        await box.fill(text);
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const r = await sent;
        await Promise.race([r?.finished().catch(() => undefined), new Promise((x) => setTimeout(x, 60_000))]);
      };
      const layouts = page.locator('[data-testid="widget"][data-shape="layout"]');

      // Step 2: the agent fills Hold review.
      await send(`call present ${JSON.stringify({ widget: 'hold-review', data: HOLD })}`);
      await layouts.first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const hold = layouts.first();
      const holdText = await hold.innerText().catch(() => '');
      check('the agent fills Hold review: payee, amount, badge, buttons and the widget named in its footer', (await hold.getAttribute('data-template')) === 'hold-review' && holdText.includes('Acme Supplies Ltd') && holdText.includes('12,500') && holdText.includes('Hold review · v1') && (await hold.getByRole('button', { name: 'Look up the account' }).count()) === 1, holdText.slice(0, 300));

      // Step 3: a button sends its reply, naming its action, and the agent calls that granted tool once.
      const acted = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/messages$/.test(r.url()), { timeout: 120_000 }));
      await hold.getByRole('button', { name: 'Look up the account' }).click();
      const reply = page.getByText('Look up this account. (action: lookup_account, query: CHQ-2219)').first();
      const replied = await reply.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const actRes = await acted;
      await Promise.race([actRes?.finished().catch(() => undefined), new Promise((x) => setTimeout(x, 60_000))]);
      // The thread as stored: the reply's turn holds one lookup_account call.
      const stored = await json(await fetch(`${agentsUrl}/chat/threads/${thread}`, { headers: J }));
      const calls = stored.messages.flatMap((m) => m.toolCalls ?? []).filter((c) => c.name === 'lookup_account').length;
      check('Look up the account sends its reply with its action, and the agent calls lookup_account once', replied && calls === 1, { replied, calls });
      await page.waitForTimeout(1500);

      // Step 4: a layout the agent composes.
      await send(`call present ${JSON.stringify({ layout: COMPOSED })}`);
      await page.getByText('Two holds are open').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const composed = layouts.filter({ hasText: 'Two holds are open' }).first();
      check('a composed layout draws, marked as composed by the agent', (await composed.getByText('Composed by the agent').count()) === 1);

      // Step 5: a widget the agent was not given.
      const before = await layouts.count();
      await send(`call present ${JSON.stringify({ widget: 'case-summary', data: { caseId: 'CASE-1', title: 'x', status: 'open' } })}`);
      await page.waitForTimeout(1500);
      check('a widget the agent was not given draws nothing', (await layouts.count()) === before, { before, after: await layouts.count() });

      // Step 6: reload.
      await page.reload({ waitUntil: 'domcontentloaded' });
      await box.waitFor({ timeout: 120_000 });
      await layouts.first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      check('after a reload both widgets draw from the stored parts', (await layouts.count()) === before, { count: await layouts.count() });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
