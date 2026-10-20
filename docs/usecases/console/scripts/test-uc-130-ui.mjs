// uc-130 an agent's Channels tab, ui layer: docs/usecases/console/agent-channels.md.
// The scripted agents service with platform sign-in: James builds in team_ops, Ravi views it.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@northfieldbank.com';
const RAVI = 'r.menon@northfieldbank.com';
const INTRANET = 'https://intranet.bank.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const post = async (path, body, headers) => (await (await fetch(`${agents}${path}`, { method: 'POST', headers, body: JSON.stringify(body) })).json()).data;
const armed = (p) => (p.catch(() => undefined), p);

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const one = await post('/v1/widget-deployments', { name: 'Intranet help (ui)', agentId: 'ag_fraud', origins: [INTRANET] }, J);
    const two = await post('/v1/widget-deployments', { name: 'Branch kiosk (ui)', agentId: 'ag_fraud', origins: [INTRANET] }, J);
    const { secret } = await post(`/v1/widget-deployments/${one.id}/keys`, { name: 'intranet server' }, J);
    const person = { email: 'm.okafor@northfieldbank.com', name: 'Maya Okafor', origin: INTRANET };
    const mint = () => fetch(`${agents}/v1/widget-deployments/${one.id}/sessions`, { method: 'POST', headers: { Authorization: `Bearer ${secret}`, 'Content-Type': 'application/json' }, body: JSON.stringify(person) });
    const { session } = (await (await mint()).json()).data;
    await fetch(`${agents}/v1/widget/${one.id}/threads`, { method: 'POST', headers: { 'X-Widget-Session': session, Origin: INTRANET } });

    const browser = await chromium.launch();
    const errors = [];
    try {
      // Step 1: the tab is Channels, and every section reads agents-service.
      const james = await signIn(browser, consoleUrl, JAMES, errors);
      await james.goto(`${consoleUrl}/agents/ag_fraud`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('agent-channels-tab-trigger').click({ timeout: 120_000 });
      const rows = james.getByTestId('widget-embed-row');
      await rows.first().waitFor({ timeout: 60_000 });
      const ids = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-id')));
      const first = rows.filter({ hasText: 'Intranet help (ui)' });
      const keys = await first.getByTestId('widget-embed-keys').innerText();
      const usage = await first.getByTestId('widget-embed-usage').innerText();
      const sections = await Promise.all(['Chat', 'Embeds on other sites', 'Versions live'].map((t) => james.getByText(t, { exact: true }).first().isVisible()));
      check('1 Channels lists the chat default, the real embeds with keys and usage, and calling workflows', [one.id, two.id].every((id) => ids.includes(id)) && ids.every((id) => id?.startsWith('wd_')) && keys.trim() === '1' && /^1 conversation/.test(usage) && /Last used/.test(usage) && sections.every(Boolean), { ids, keys, usage, sections });

      // Step 2: a viewer gets no Retire or Pause.
      const ravi = await signIn(browser, consoleUrl, RAVI, errors);
      await ravi.goto(`${consoleUrl}/agents/ag_fraud?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await ravi.getByTestId('widget-embed-row').first().waitFor({ timeout: 60_000 });
      const raviButtons = (await ravi.getByTestId('widget-retire').count()) + (await ravi.getByRole('button', { name: 'Pause' }).count());
      check('2 a viewer is offered no Retire or Pause', raviButtons === 0, { raviButtons });

      // Step 3: James retires the first embed; its page is refused from then on.
      await first.getByTestId('widget-retire').click();
      const dialog = james.getByRole('dialog');
      // Retiring is the channel API's own call (c-245).
      const saved = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/channels/${one.id}/retire`), { timeout: 60_000 }));
      await dialog.getByRole('button', { name: 'Retire' }).click();
      const status = (await saved)?.status();
      const shown = await first.getByText('Retired', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const actions = await first.getByRole('button').count();
      const refused = await mint();
      const code = (await refused.json()).error?.code;
      check('3 a retired embed shows Retired with no actions, and its page is refused', status === 200 && shown && actions === 0 && refused.status === 409 && code === 'widget_retired', { status, shown, actions, refused: refused.status, code });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
