// uc-532 An account admin saves a model provider key on Settings and a model call signs in to the provider with it,
// ui layer: docs/usecases/models-service/an-account-admin-saves-a-model.md (c-509). The run's own demo stack: platform
// sign-in, models-service and the fake OpenAI, which refuses any credential but FAKE_OPENAI_KEY. Sam is the account
// admin (an admin on the Security team); James is a builder of Operations.
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { FAKE_OPENAI_KEY, MODELS_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const models = `http://127.0.0.1:${MODELS_PORT}`;
const PASSWORD = 'northfield-demo';
const SAM = 's.adeyemi@harborpine.example';
const JAMES = 'j.richardson@harborpine.example';
// The alias agents would pick, on OpenAI's gpt-4.1-mini (the fake answers any model id).
const ALIAS = 'uc532-mini';
const MODEL = 'gpt-4.1-mini';
const KEY = 'OPENAI';
const SHOTS = evidenceDir('509', 'uc-532');
mkdirSync(SHOTS, { recursive: true });
const signIn = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// agents-service's token for models-service's admin routes (dev key, dev only): what make demo-model drives.
const serviceToken = (tenant) =>
  execFileSync('uv', ['run', 'python', '-c', `from ops_identity import dev_service_signer, mint_service_token; print(mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="${tenant}", ttl_s=600))`], { cwd: join(ROOT, 'services/models-service'), encoding: 'utf8' }).trim();

/** Waits for `text` on `page`; on a timeout, saves the page and fails with what it showed instead. */
async function see(page, text, name) {
  try {
    await page.getByText(text).first().waitFor({ timeout: 60_000 });
  } catch (e) {
    await page.screenshot({ path: join(SHOTS, `failed-${name}.png`), fullPage: true }).catch(() => undefined);
    const shown = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 400);
    throw new Error(`${name}: "${text}" not shown; the page showed: ${shown}`, { cause: e });
  }
}

await withUiStack(
  async (consoleUrl) => {
    const sam = await signIn(SAM);
    const tenant = sam.principal.tenantId;
    const N = { Authorization: `Bearer ${sam.token}`, 'X-Team-Id': 'team_security' };
    const J = { Authorization: `Bearer ${(await signIn(JAMES)).token}`, 'X-Team-Id': 'team_ops' };
    const S = { Authorization: `Bearer ${serviceToken(tenant)}`, 'Content-Type': 'application/json' };
    // A connection to the run's fake OpenAI that signs in with OPENAI, and an alias on gpt-4.1-mini through it.
    const fake = (await data(await fetch(`${models}/v1/models/providers`, { headers: S }))).find((p) => p.id === 'openai-local').baseUrl;
    const made = await data(await fetch(`${models}/v1/models/providers`, { method: 'POST', headers: S, body: JSON.stringify({ name: 'openai-uc532', type: 'openai-compatible', baseUrl: fake, keyRef: KEY }) }));
    await data(await fetch(`${models}/v1/models/aliases`, { method: 'POST', headers: S, body: JSON.stringify({ name: ALIAS, kind: 'chat', providerId: made.id, modelId: MODEL, clearedSensitivity: 'confidential' }) }));
    const chat = () =>
      fetch(`${models}/v1/models/chat/completions`, {
        method: 'POST',
        headers: { Authorization: 'Bearer mk_dev_agents', 'X-Tenant-Id': tenant, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: ALIAS, messages: [{ role: 'system', content: 'You are Wire Desk, a bank assistant.' }, { role: 'user', content: 'What does an outgoing wire cost?' }] }),
      });

    const before = await chat();
    const missing = await before.json();
    check('1 with no key saved, a call to gpt-4.1-mini is refused naming the key, before any provider call', before.status === 503 && missing.error?.code === 'provider_key_missing' && missing.error.message.includes(KEY), { status: before.status, body: missing });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      await page.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await see(page, 'No model provider keys yet', 'empty');
      const save = async (value, replace) => {
        if (replace) {
          await page.getByTestId(`provider-keys`).locator('tr', { hasText: KEY }).getByRole('button').last().click();
          await page.getByRole('menuitem', { name: 'Replace key' }).click();
        } else {
          await page.getByTestId('provider-key-add').click();
          await page.getByLabel('Name').fill(KEY);
        }
        await page.getByLabel('Key', { exact: true }).fill(value);
        await page.getByTestId('provider-key-save').click();
        await page.getByRole('dialog').waitFor({ state: 'detached', timeout: 30_000 });
      };
      await save(FAKE_OPENAI_KEY, false);
      await page.getByTestId('provider-keys').locator('tr', { hasText: KEY }).waitFor({ timeout: 30_000 });
      await page.screenshot({ path: join(SHOTS, 'saved-1280.png'), fullPage: true });
      const shown = await page.content();
      const after = await chat();
      const answer = await after.json();
      const listed = await (await fetch(`${models}/v1/provider-keys`, { headers: N })).text();
      check(
        '2 the key Sam saves on Model providers signs the next call to gpt-4.1-mini, and neither the page nor the list shows it',
        after.status === 200 && Boolean(answer.choices?.[0]?.message?.content) && !shown.includes(FAKE_OPENAI_KEY) && !listed.includes(FAKE_OPENAI_KEY),
        { status: after.status, answer: answer.choices?.[0]?.message?.content ?? answer, listed },
      );

      await save('sk-not-the-fakes-key', true);
      const wrong = await chat();
      await save(FAKE_OPENAI_KEY, true);
      const right = await chat();
      const rows = await data(await fetch(`${models}/v1/provider-keys`, { headers: N }));
      check('3 a replaced value is what reaches the provider: a wrong key is refused by it, the right one answers again', wrong.status === 502 && right.status === 200 && rows[0]?.version === 3, { wrong: wrong.status, right: right.status, rows });

      const gone = await fetch(`${models}/v1/provider-keys/${KEY}`, { method: 'DELETE', headers: N });
      check('4 a key a connection signs in with is not removed', gone.status === 409 && (await gone.json()).error?.code === 'key_in_use', gone.status);

      const builder = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await builder.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await see(builder, 'Only an account admin', 'builder');
      await builder.screenshot({ path: join(SHOTS, 'builder-1280.png'), fullPage: true });
      const theirs = await fetch(`${models}/v1/provider-keys`, { headers: J });
      const set = await fetch(`${models}/v1/provider-keys/${KEY}`, { method: 'PUT', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ value: 'sk-james' }) });
      const still = await chat();
      check('5 a builder sees no key on the page and cannot list or set one', theirs.status === 403 && set.status === 403 && still.status === 200 && (await builder.content()).indexOf(KEY) === -1, { list: theirs.status, set: set.status, still: still.status });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
