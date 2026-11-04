// uc-611 a developer builds a REST tool and runs it for real, ui layer: docs/usecases/tools-service/a-developer-builds-a-rest-tool.md.
// James opens a published REST tool with no connection, runs it in Mock, picks the payments connection on the page and
// runs a form-encoded write and a search for real against the fake bank's Stripe-shaped stand-in, then saves a key in a
// header and sees every problem at once. The module and the connection are set up through the API.
import { execFileSync } from 'node:child_process';
import { TOOLS_PORT, approveToolReview, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, connection } from '../../lib/connection_ui.mjs';
import { JAMES, PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);
const tools = `http://127.0.0.1:${TOOLS_PORT}/v1/tool-modules`;
const EMAIL = `jo.reyes+${RUN}@example.com`;
const shots = evidenceDir('591', 'ui');

async function send(method, path, headers, body) {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${JSON.stringify(out.error ?? out).slice(0, 300)}`);
  return out.data;
}

/** Presses Run and returns the test call's answer as the page got it. */
async function run(page, moduleId) {
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/test`), { timeout: 60_000 });
  await page.getByTestId('run').click();
  const res = await answered;
  return { status: res.status(), ...((await res.json().catch(() => ({}))).data ?? {}) };
}

/** The page at 1280 in light and dark, scrolled to `region` as a person would be, to set beside its mock frame. */
async function shoot(page, name, region) {
  if (region) await page.getByTestId(region).first().scrollIntoViewIfNeeded();
  for (const theme of ['light', 'dark']) {
    await page.evaluate((t) => document.documentElement.classList.toggle('dark', t === 'dark'), theme);
    // The theme's colours ease in; a shot taken at once catches them half way.
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${shots}/${name}-1280-${theme}.png` });
  }
  await page.evaluate(() => document.documentElement.classList.remove('dark'));
}

await withUiStack(
  async (consoleUrl, stack) => {
    // 1. A published module with a form-encoded write and a search, no connection yet; a Bearer connection on the bank.
    await allowBank(stack.bank);
    const J = await as(JAMES);
    const base = `https://${stack.bank.host}`;
    // A team admin makes connections; Priya holds Admin in Operations.
    const conn = await connection(await as(PRIYA), `Bank key ${RUN}`, 'bearer', { sandbox: { secretValues: { token: 'test-bearer-token' } } }, { baseUrl: base, testPath: '/auth/bearer' });
    const mod = await send('POST', '/blank', J, { displayName: `Payments ${RUN}`, name: `uc611-${RUN}`, type: 'http' });
    await send('POST', `/${mod.id}/operations`, J, {
      name: 'create_customer', description: 'Creates a customer with an email.', access: 'write', method: 'POST',
      url: `${base}/auth/bearer/customers`, bodyEncoding: 'form', body: JSON.stringify({ email: '{{email}}', 'metadata[source]': 'ops_ai' }),
    }); // prettier-ignore
    await send('POST', `/${mod.id}/operations`, J, { name: 'search_customers', description: 'Customers with an email.', access: 'read', method: 'GET', url: `${base}/auth/bearer/customers/search?email={email}` });
    await send('POST', `/${mod.id}/reviews`, J, { note: 'uc-611' });
    await approveToolReview(mod.id, await as('n.petrov@harborpine.example', 'team_security'), J);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await page.setViewportSize({ width: 1280, height: 900 });
      const opPage = (op) => page.goto(`${consoleUrl}/tools/${mod.id}/operations/${op}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await opPage('create_customer');
      const real = page.getByTestId('run-mode').getByRole('radio', { name: 'Real' });
      await real.waitFor({ timeout: 120_000 });
      // A published tool runs Real with or without a connection that signs in.
      for (let i = 0; i < 30 && (await real.isDisabled()); i++) await page.waitForTimeout(1000);
      check('2 Real can be chosen on the published tool', !(await real.isDisabled()), await page.getByTestId('run-help').innerText());
      await shoot(page, 'no-connection');

      await page.locator('#t-email').fill(EMAIL);
      const mock = await run(page, mod.id);
      await page.getByTestId('run-badge').waitFor({ timeout: 30_000 });
      await page.getByRole('tab', { name: 'Request sent' }).click().catch(() => undefined);
      const mockSent = await page.getByTestId('test-request').innerText().catch(() => '');
      check('3 Mock answers and sends nothing', mock.status === 200 && mock.decision === 'allow' && !mock.request && (await page.getByTestId('run-badge').innerText()).includes('Mock') && /Nothing was sent/.test(mockSent), { mock, mockSent });

      await page.getByTestId('module-connection-select').click();
      await page.getByRole('option', { name: new RegExp(`Bank key ${RUN}`) }).click();
      const signs = await page.getByText(`Signs every Real request in to ${stack.bank.host}`).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('4 the picked connection signs Real requests in to the bank', signs && !(await real.isDisabled()), signs);
      await shoot(page, 'before-run');

      await real.click();
      const made = await run(page, mod.id);
      await page.getByTestId('run-badge').waitFor({ timeout: 30_000 });
      const badge = await page.getByTestId('run-badge').innerText();
      check('5 Real makes the customer, badged Real', made.status === 200 && made.stubbed === false && /^cus_/.test(made.output?.id ?? '') && made.output?.email === EMAIL && badge.includes('Real'), { status: made.status, stubbed: made.stubbed, output: made.output, badge });
      await shoot(page, 'real-answered', 'run-badge');

      await page.getByRole('tab', { name: 'Request sent' }).click();
      const sent = await page.getByTestId('test-request').innerText();
      const whole = await page.locator('main').innerText();
      check(
        '6 Request sent shows the form body with the key hidden',
        /application\/x-www-form-urlencoded/.test(sent) && sent.includes(`email=${encodeURIComponent(EMAIL).replace(/%20/g, '+')}`) && !whole.includes('test-bearer-token'),
        sent.slice(0, 600),
      );
      await shoot(page, 'request-sent', 'test-request');

      await opPage('search_customers');
      await page.getByTestId('run-mode').getByRole('radio', { name: 'Real' }).click({ timeout: 120_000 });
      await page.locator('#t-email').fill(EMAIL);
      const found = await run(page, mod.id);
      check('7 the search finds the customer for real', found.status === 200 && (found.output?.data ?? []).some((c) => c.id === made.output?.id), found.output);

      await opPage('create_customer');
      await page.getByRole('tab', { name: 'Headers' }).click({ timeout: 120_000 });
      const headers = page.getByTestId('http-headers');
      for (const [k, v] of [['Authorization', 'Bearer sk_live_51abc'], ['Content-Type', 'application/json']]) {
        await headers.getByRole('button', { name: 'Add header' }).click();
        await headers.getByLabel('Header name', { exact: true }).last().fill(k);
        await headers.getByLabel('Header value', { exact: true }).last().fill(v);
      }
      await page.getByTestId('workbench-stage').click();
      const problems = page.getByTestId('save-problems');
      await problems.waitFor({ timeout: 60_000 });
      const said = await problems.innerText();
      const kept = await headers.getByLabel('Header value', { exact: true }).last().inputValue();
      check('8 one message lists both problems and keeps the edits', /2 problems/.test(said) && /connection/.test(said) && /Content-Type is set by the body encoding/.test(said) && kept === 'application/json', said);
      await shoot(page, 'save-problems', 'save-problems');

      // 17. A Real run stopped before sending (the app had no account signed in): Request sent says so, with the reason,
      // never that a mock answered.
      await opPage('search_customers');
      await page.route('**/v1/tool-modules/*/test', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { decision: 'allow', stubbed: false, status: 409, latencyMs: 1, bound: [], wouldPause: false, output: { error: { code: 'PLUGIN_DISABLED', message: 'The app has no account signed in yet.' } }, masked: [], callId: 'gwc_refused', log: [{ atMs: 0, message: 'Refused: the app has no account signed in yet' }] } }) }), { times: 1 });
      await page.locator('#t-email').fill(EMAIL);
      await page.getByTestId('run').click();
      await page.getByRole('tab', { name: 'Request sent' }).click({ timeout: 60_000 }).catch(async (e) => {
        console.log('after the refused run:', ((await page.locator('main').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ').slice(0, 900));
        throw e;
      });
      const none = ((await page.getByTestId('test-request-none').innerText({ timeout: 30_000 }).catch(() => '')) ?? '').trim();
      check('17 a refused run says nothing was sent because it stopped before sending, with the reason', /stopped before the request went out/.test(none) && /no account signed in/.test(none) && !/mock/.test(none), none);

      // 15. Group F in the console: the tool page's address comes from the app (its field reads App), and New module
      // names the app it calls and sends no type; the address shown is the app's base address.
      const appField = await page.getByRole('combobox', { name: 'App' }).count();
      const address = await page.locator('#http-url').inputValue();
      await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('new-module').click({ timeout: 120_000 });
      const dialog = page.getByTestId('new-module-dialog');
      await dialog.getByLabel('Display name').fill(`Ledger ${RUN}`);
      await dialog.getByRole('combobox', { name: 'App' }).click();
      await page.getByRole('option', { name: new RegExp(`Bank key ${RUN}`) }).click();
      const blank = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/v1/tool-modules/blank'), { timeout: 60_000 });
      await page.getByTestId('new-module-save').click();
      const body = JSON.parse((await blank).postData() ?? '{}');
      await page.waitForURL((u) => /^\/tools\/[^/]+$/.test(u.pathname) && !u.pathname.endsWith('/calls'), { timeout: 60_000 });
      const blankMod = await send('GET', `/${new URL(page.url()).pathname.split('/').pop()}`, J);
      const header = ((await page.getByTestId('page-description').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
      await shoot(page, 'new-module-app');
      check(
        '15 the tool page reads App and its address is the app’s; New module names the app and sends no type',
        appField >= 1 && address.startsWith(base) && body.connectionId === conn.id && !('type' in body) && blankMod.connection?.id === conn.id && header.includes(base),
        { appField, address, body, connection: blankMod.connection, header: header.slice(0, 200) },
      );
      // 16. A tool saved before sign-in headers were refused still carries one: its page says to move the key to the app.
      // The row is written straight into the run's database, as such a tool was left; two tools with different keys
      // keep tools-service's start-up move from taking it off.
      const legacy = await send('POST', '/blank', J, { displayName: `Legacy ${RUN}`, name: `uc611-legacy-${RUN}` });
      for (const name of ['legacy_one', 'legacy_two']) await send('POST', `/${legacy.id}/operations`, J, { name, description: 'A legacy read.', access: 'read', method: 'GET', url: `${base}/auth/bearer/customers` });
      const db = process.env.OPS_INFRA === 'external' ? `postgresql://ops:ops@postgres:5432/${process.env.OPS_USECASE_DB ?? 'ops_usecase'}` : `postgresql://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${process.env.OPS_USECASE_DB ?? 'ops_usecase'}`;
      execFileSync('psql', [db, '-v', 'ON_ERROR_STOP=1', '-qc',
        `UPDATE module_operations SET headers = '[{"key": "X-Api-Key", "value": "{{ONE_KEY}}"}]' WHERE module_id = '${legacy.id}' AND name = 'legacy_one';` +
        `UPDATE module_operations SET headers = '[{"key": "X-Api-Key", "value": "{{OTHER_KEY}}"}]' WHERE module_id = '${legacy.id}' AND name = 'legacy_two';`]); // prettier-ignore
      const served = (await send('GET', `/${legacy.id}`, J)).operations?.find((o) => o.name === 'legacy_one')?.signInHeader ?? null;
      await page.goto(`${consoleUrl}/tools/${legacy.id}/operations/legacy_one`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('module-test-panel').waitFor({ timeout: 120_000 }).catch(() => undefined);
      const notice = ((await page.getByTestId('sign-in-header').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
      await opPage('create_customer');
      const cleanTool = await page.getByTestId('sign-in-header').count();
      check('16 a tool still sending a sign-in header says to move it to the app; a clean tool says nothing', served === 'X-Api-Key' && /This tool sends a sign-in header; move it to the app/.test(notice) && /X-Api-Key/.test(notice) && cleanTool === 0, { served, notice, cleanTool });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
    void conn;
  },
  CONNECTION_STACK,
);

finish();
