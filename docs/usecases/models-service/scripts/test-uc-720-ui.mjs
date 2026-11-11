// uc-720 A refused model call in chat says what went wrong with the provider and what to do, ui layer:
// docs/usecases/models-service/a-refused-model-call-says-what-to-do.md. The run's demo stack: platform sign-in,
// agents-service, models-service and the fake OpenAI, which refuses any credential but FAKE_OPENAI_KEY. Priya is an admin
// who manages settings; Ravi is a viewer of Operations. Screenshots go to evidenceDir('720', 'uc-720').
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, MODELS_PORT, PLATFORM_PORT, check, chromium, consoleSignIn, evidenceDir, finish, replyDone, withUiStack } from '@ops-ai/usecase-runner/harness';

const models = `http://127.0.0.1:${MODELS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const KEY = 'OPENAI';
const WRONG = 'sk-not-the-fakes-key-7731';
const SHOTS = evidenceDir('720', 'uc-720');
mkdirSync(SHOTS, { recursive: true });
const signIn = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data;

/** A new chat of the person's own with the first agent they may chat with, made through agents-service's API. */
async function thread(email) {
  const H = { Authorization: `Bearer ${(await signIn(email)).token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
  const listed = await (await fetch(`${agents}/chat/agents`, { headers: H })).json();
  const agent = listed.data?.[0];
  if (!agent) throw new Error(`${email} may chat with no agent: ${JSON.stringify(listed).slice(0, 300)}`);
  const made = await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: H, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) })).json();
  if (!made.data?.id) throw new Error(`${email} could not start a chat with ${agent.id}: ${JSON.stringify(made).slice(0, 300)}`);
  return made.data.id;
}

/** Asks in the person's chat and returns the reply's error text once the reply ends. */
async function ask(page, consoleUrl, email) {
  await page.goto(`${consoleUrl}/chat/${await thread(email)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const box = page.getByRole('textbox', { name: 'Message' });
  await box.waitFor({ timeout: 120_000 });
  await box.fill('What does an outgoing wire cost?');
  const sent = page.waitForResponse((r) => r.url().includes('/messages') && r.request().method() === 'POST', { timeout: 60_000 }).catch(() => null);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await replyDone(await sent, 90_000);
  const error = page.getByTestId('reply-error').last();
  await error.waitFor({ timeout: 90_000 });
  return (await error.innerText()).trim();
}

const wide = (page) => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);

async function shots(page, name) {
  const out = {};
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.getByTestId('reply-error').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`), fullPage: false });
    out[width] = { text: (await page.getByTestId('reply-error').last().innerText()).trim(), sideways: await wide(page) };
  }
  return out;
}

await withUiStack(
  async (consoleUrl) => {
    const priya = await signIn(PRIYA);
    const N = { Authorization: `Bearer ${priya.token}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' };
    // The agents' default alias runs on openai-local; it now signs in with a key the fake refuses.
    const saved = await fetch(`${models}/v1/provider-keys/${KEY}`, { method: 'PUT', headers: N, body: JSON.stringify({ value: WRONG }) });
    const local = (await (await fetch(`${models}/v1/models/providers`, { headers: N })).json()).data.find((p) => p.id === 'openai-local');
    const bound = await fetch(`${models}/v1/models/providers/openai-local`, { method: 'PUT', headers: N, body: JSON.stringify({ baseUrl: local.baseUrl, keyRef: KEY }) });
    check('0 set-up: a wrong key is saved and openai-local signs in with it', saved.status === 200 && bound.status === 200, { saved: saved.status, bound: await bound.text() });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const admin = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const said = await ask(admin, consoleUrl, PRIYA);
      const link = admin.getByRole('link', { name: 'Open Model providers' }).last();
      const href = await link.getAttribute('href', { timeout: 10_000 }).catch(() => null);
      check(
        '1 an admin reads that the provider refused the key and is offered Settings > Model providers',
        said === "The model provider refused the account's key. Check or replace the key on Settings > Model providers." && href === '/settings/workspace/model-providers' && !(await admin.content()).includes(WRONG),
        { said, href },
      );
      await admin.reload({ waitUntil: 'domcontentloaded' });
      await admin.getByTestId('reply-error').last().waitFor({ timeout: 90_000 });
      const reloaded = (await admin.getByTestId('reply-error').last().innerText()).trim();
      check('2 after a reload the admin reads the same sentence', reloaded === said, { reloaded });
      const adminShots = await shots(admin, 'admin');

      const member = await consoleSignIn(browser, consoleUrl, RAVI, PASSWORD, errors);
      const theirs = await ask(member, consoleUrl, RAVI);
      const memberLinks = await member.getByRole('link', { name: 'Open Model providers' }).count();
      check(
        '3 a member is told to ask an admin and is not offered the settings page',
        theirs === "The model provider refused the account's key. Ask an admin to check the key on Settings > Model providers." && memberLinks === 0,
        { theirs, memberLinks },
      );
      const memberShots = await shots(member, 'member');
      const all = { ...Object.fromEntries(Object.entries(adminShots).map(([w, v]) => [`admin-${w}`, v])), ...Object.fromEntries(Object.entries(memberShots).map(([w, v]) => [`member-${w}`, v])) };
      check('4 at 1440 and 390 the same sentence shows and nothing scrolls sideways', Object.values(all).every((v) => !v.sideways && (v.text === said || v.text === theirs)), all);
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
