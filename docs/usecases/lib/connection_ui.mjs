// What the connection ui scripts share (c-553): a connection set up per environment through tools-service, as its api
// layer sets one (docs/usecases/tools-service/scripts/connection_calls.py), and Test the team account pressed on the
// connection's page. The console's connect dialog runs on the mock only, so keys are entered through the API. The page
// needs the console switch NEXT_PUBLIC_OPS_PERSONAL_SIGNIN (CONNECTION_STACK).
import { TOOLS_PORT } from '@ops-ai/usecase-runner/harness';

import { as } from './workflow_ui.mjs';

export const tools = `http://127.0.0.1:${TOOLS_PORT}`;
/** Platform sign-in, tools-service with the core bank stand-in on https, and the connection page switched on. */
export const CONNECTION_STACK = { platform: true, tools: { bank: 'core' }, consoleSwitches: { NEXT_PUBLIC_OPS_PERSONAL_SIGNIN: '1' } };

async function send(method, path, headers, body) {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
}

/** Security lists the bank stand-in's host and range, so a test may reach it. */
export async function allowBank(bank) {
  const sam = await as('s.adeyemi@harborpine.example', 'team_security');
  await send('POST', '/v1/egress/hosts', sam, { value: bank.host, note: 'connection use case' });
  await send('POST', '/v1/egress/ranges', sam, { value: bank.range, note: 'connection use case' });
}

/**
 * A connection of `kind` with each environment's `{ settings, secretValues }` set as `headers`' person, bound to
 * `baseUrl` and tested at `testPath`. Throws on a refused setup, so a script fails at the step that needs it.
 */
export async function connection(headers, name, kind, environments, { baseUrl, testPath }) {
  const made = await send('POST', '/v1/connections', headers, { name, authKind: kind });
  if (made.status !== 201) throw new Error(`creating ${name}: ${made.status}`);
  let conn = made.data;
  for (const [env, body] of Object.entries(environments)) {
    const settings = { baseUrl, testPath, ...(body.settings ?? {}) };
    const put = await send('PUT', `/v1/connections/${conn.id}/environments/${env}`, headers, { revision: conn.revision, ...body, settings });
    if (put.status !== 200) throw new Error(`setting ${name} ${env}: ${put.status}`);
    conn = put.data ?? conn;
  }
  return conn;
}

/** Opens the connection's page, presses Test the team account and returns what the Health section says. */
export async function testTeamAccount(page, consoleUrl, id) {
  await page.goto(`${consoleUrl}/tools/connections/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const button = page.getByTestId('test-team');
  await button.waitFor({ timeout: 90_000 });
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
  await button.click();
  await answered;
  const health = page.getByTestId('health');
  await health.waitFor({ timeout: 60_000 });
  return {
    status: await health.getAttribute('data-status'),
    said: ((await health.innerText()) ?? '').replace(/\s+/g, ' '),
    page: ((await page.locator('main').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' '),
  };
}
