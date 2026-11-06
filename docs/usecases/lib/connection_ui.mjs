// What the connection ui scripts share: a custom app with its live account and, where asked, a sandbox account, set up
// through tools-service as its api layer sets one (docs/usecases/lib/connection_calls.py), and Test pressed on the
// app page's Keys row. Keys are entered through the API, as the api layer sets them.
import { TOOLS_PORT } from '@ops-ai/usecase-runner/harness';

import { as } from './workflow_ui.mjs';

export const tools = `http://127.0.0.1:${TOOLS_PORT}`;
/** Platform sign-in and tools-service with the core bank stand-in on https. */
export const CONNECTION_STACK = { platform: true, tools: { bank: 'core' } };

async function send(method, path, headers, body) {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
}

/** Security lists the bank stand-in's host and range, so a test may reach it. */
export async function allowBank(bank) {
  const sam = await as('s.adeyemi@harborpine.example', 'team_security');
  await send('POST', '/v1/egress/hosts', sam, { value: bank.host, note: 'connection use case' });
  // The core bank's certificate-only listener is a second host on the same address.
  if (bank.mtlsHost) await send('POST', '/v1/egress/hosts', sam, { value: bank.mtlsHost, note: 'connection use case' });
  await send('POST', '/v1/egress/ranges', sam, { value: bank.range, note: 'connection use case' });
}

/** An account's address under its app. */
export const accountPath = (account) => `/v1/apps/${encodeURIComponent(account.appId)}/accounts/${encodeURIComponent(account.id)}`;

async function keys(headers, account, body, { baseUrl, testPath }, what) {
  const settings = { baseUrl, testPath, ...(body.settings ?? {}) };
  const put = await send('PATCH', accountPath(account), headers, { revision: account.revision, ...body, settings });
  if (put.status !== 200) throw new Error(`setting ${what}: ${put.status}`);
  return put.data ?? account;
}

/**
 * A custom app of `kind` and its accounts, each `{ settings, secretValues }` set as `headers`' person, bound to
 * `baseUrl` and tested at `testPath`: `live` is the app's first account, `sandbox` a sandbox account beside it (the one
 * test runs use). With only a sandbox, the app's first account is that sandbox. Answers the first account, with the
 * sandbox under `sandboxAccount` when both were made. Throws on a refused setup, so a script fails at the step that
 * needs it.
 */
export async function connection(headers, name, kind, accounts, at) {
  const onlySandbox = !accounts.live;
  const made = await send('POST', '/v1/apps', headers, { name, authKind: kind, signIn: 'team', sandbox: onlySandbox });
  if (made.status !== 201) throw new Error(`creating ${name}: ${made.status}`);
  const first = await keys(headers, made.data, onlySandbox ? accounts.sandbox : accounts.live, at, name);
  if (onlySandbox || !accounts.sandbox) return first;
  const added = await send('POST', `/v1/apps/${encodeURIComponent(first.id)}/accounts`, headers, { name: `${name} sandbox`, sandbox: true });
  if (added.status !== 201) throw new Error(`adding ${name}'s sandbox account: ${added.status}`);
  return { ...first, sandboxAccount: await keys(headers, added.data, accounts.sandbox, at, `${name} sandbox`) };
}

/**
 * Opens the app's page and runs Test now from the Accounts tab's row menu: the team's default account, or with
 * `{ own: true }` the caller's own sign-in. Answers the test's status from the service's answer and what the page said
 * of it (the toast: whether it works, the HTTP status, the reason and whose sign-in it used).
 */
export async function testTeamAccount(page, consoleUrl, account, { own = false } = {}) {
  await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(account.appId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const menu = page.locator(own ? '[data-testid^="account-menu-"][data-mine="true"]' : '[data-testid^="account-menu-"][data-default="true"]').first();
  await menu.waitFor({ timeout: 90_000 });
  await menu.click();
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/accounts\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
  await page.getByRole('menuitem', { name: 'Test now' }).click();
  const res = await answered;
  const health = res ? ((await res.json().catch(() => ({}))).data?.health ?? {}) : {};
  const toast = page.locator('[data-sonner-toast]').last();
  await toast.waitFor({ timeout: 30_000 }).catch(() => {});
  const said = ((await toast.innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
  return {
    status: health.status ?? null,
    said: health.status === 'ok' ? said : `Failed ${said}`,
    page: ((await page.locator('main').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' '),
  };
}
