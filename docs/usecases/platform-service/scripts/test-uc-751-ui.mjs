// uc-751, ui layer: docs/usecases/platform-service/a-new-workspace-chats-and-writes.md, steps 3, 4 and 11. Headless
// Chromium against a running console and stack started on a fresh database (CONSOLE_URL, PLATFORM_URL, MODELS_URL).
// The account admin (Sam Adeyemi, admin of the Security team) with no model key sets chat up from the overview card in
// three steps: provider, the OpenAI key (OPENAI_API_KEY) saved and tested, then a chat model from the key's list. At
// 1440 and at 390 wide; each width starts with no key. Approvals then shows the makers' ask-first switch off.
// SHOTS names the folder each step's screenshot goes to.
import { mkdirSync } from 'node:fs';

import { check, chromium, consoleSignIn, finish } from '@ops-ai/usecase-runner/harness';

const CONSOLE = process.env.CONSOLE_URL ?? 'http://localhost:3016';
const PLATFORM = process.env.PLATFORM_URL ?? 'http://localhost:8710';
const MODELS = process.env.MODELS_URL ?? 'http://localhost:8730';
const SHOTS = process.env.SHOTS ?? 'test-results/first-run';
const EMAIL = 's.adeyemi@harborpine.example';
const PASSWORD = process.env.OPS_PLATFORM_DEMO_PASSWORD ?? 'northfield-demo';
const KEY = process.env.OPENAI_API_KEY;
mkdirSync(SHOTS, { recursive: true });

async function asAdmin() {
  const r = await fetch(`${PLATFORM}/v1/auth/sign-in`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: EMAIL, password: PASSWORD }) });
  const token = (await r.json()).data.token;
  return (method, path, body) =>
    fetch(`${MODELS}/v1${path}`, { method, headers: { authorization: `Bearer ${token}`, 'x-team-id': 'team_security', 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
}

/** Back to a workspace with no model key: the setup connection lets go of its key, then every key is removed. */
async function noKeys(call) {
  for (const c of (await (await call('GET', '/models/providers')).json()).data ?? []) {
    if (c.name.startsWith('default-') && c.keyRef) await call('PUT', `/models/providers/${c.id}`, { baseUrl: c.baseUrl, keyRef: null, apiVersion: c.apiVersion ?? null });
  }
  for (const k of (await (await call('GET', '/provider-keys')).json()).data ?? []) await call('DELETE', `/provider-keys/${k.name}`);
  return ((await (await call('GET', '/provider-keys')).json()).data ?? []).length;
}

if (!KEY) {
  check('OPENAI_API_KEY is set: the use case needs the company’s own key', false);
  finish();
}
const call = await asAdmin();
const browser = await chromium.launch();
const errors = [];
try {
  for (const [w, h] of [
    [1440, 900],
    [390, 844],
  ]) {
    check(`${w}: the workspace starts with no model key`, (await noKeys(call)) === 0);
    const page = await consoleSignIn(browser, CONSOLE, EMAIL, PASSWORD, errors);
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`${CONSOLE}/`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const card = page.getByTestId('model-setup');
    const shown = await card.waitFor({ timeout: 120_000 }).then(() => true, () => false);
    check(`${w}: the overview asks the admin to set up the AI model`, shown);
    await page.screenshot({ path: `${SHOTS}/0-setup-card-${w}.png` });
    await page.getByTestId('model-setup-start').click();
    await page.getByTestId('model-setup-steps').waitFor();
    await page.screenshot({ path: `${SHOTS}/1-provider-${w}.png` });
    // Azure OpenAI asks for its endpoint before it moves on; OpenAI does not.
    await page.getByText('Azure OpenAI', { exact: true }).click();
    await page.getByTestId('model-setup-next').click();
    const asked = await page.getByText('Enter the resource’s endpoint', { exact: false }).waitFor({ timeout: 10_000 }).then(() => true, () => false);
    check(`${w}: Azure OpenAI without its endpoint is held at step one`, asked);
    await page.getByText('OpenAI', { exact: true }).click();
    await page.getByTestId('model-setup-next').click();
    await page.getByTestId('model-setup-key').fill(KEY);
    await page.screenshot({ path: `${SHOTS}/2-key-${w}.png` });
    await page.getByTestId('model-setup-test').click();
    const listed = await page.getByTestId('model-setup-model').waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check(`${w}: the key is tested and step three lists its models`, listed && (await page.getByText('The provider accepted the key.').count()) > 0);
    await page.getByTestId('model-setup-model').click();
    const option = page.getByRole('option', { name: /^gpt-4\.1-mini$|^gpt-4o-mini$/ }).first();
    await option.waitFor({ timeout: 10_000 });
    const model = (await option.innerText()).trim();
    await option.click();
    await page.getByRole('listbox').waitFor({ state: 'detached', timeout: 5_000 }).catch(() => undefined);
    await page.screenshot({ path: `${SHOTS}/3-chat-model-${w}.png` });
    const saved = page.waitForResponse((r) => r.url().endsWith('/v1/models/chat-model') && r.request().method() === 'PUT', { timeout: 30_000 });
    await page.getByTestId('model-setup-use').click();
    const res = await saved;
    const body = await res.json();
    check(`${w}: chat is pointed at ${model}`, res.status() === 200 && body.data.model === model && body.data.aliases.join() === 'default,assistant', body);
    const gone = await card.waitFor({ state: 'detached', timeout: 30_000 }).then(() => true, () => false);
    check(`${w}: the setup card is gone once chat is set up`, gone);
    await page.screenshot({ path: `${SHOTS}/4-done-${w}.png` });
    await page.goto(`${CONSOLE}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const sw = page.getByTestId('approvals-makers-switch');
    const there = await sw.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check(`${w}: Approvals shows the makers’ ask-first switch, off in a new workspace`, there && (await sw.getAttribute('aria-checked')) === 'false');
    await sw.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/5-approvals-switch-${w}.png` });
    await page.context().close();
  }
  check('no page errors', errors.length === 0, errors);
} finally {
  await browser.close();
}
finish();
