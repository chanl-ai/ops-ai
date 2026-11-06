// uc-396 a builder adds an MCP server behind OAuth by its address and signs in once, ui layer:
// docs/usecases/tools-service/mcp-sign-in.md. The server is added by its address through the API, as the api layer adds
// it. Priya, an Operations admin, opens its app page, sets it to each person's own account in Settings, connects hers
// through the pop-up from her row, and her row says whom she is connected as; Test then works with her account.
// The browser reaches the bank stand-in's sign-in host on its own address, as tools-service does by its name map.
import { asRole, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, testTeamAccount, tools } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);
const send = async (method, path, headers, body) => {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await asRole('admin');
    const server = `https://${stack.bank.host}/mcp/screening`;
    const made = await send('POST', '/v1/apps', P, { serverUrl: server, name: `uc396 screening ${RUN}`, signIn: 'team', sandbox: false });
    if (made.status !== 201) throw new Error(`adding the MCP server: ${made.status}`);
    // Test reads a path on the server's host with the account's token; the stand-in's /auth/oauth says which client
    // the token is for.
    const put = await send('PATCH', `/v1/apps/${made.data.appId}/accounts/${made.data.id}`, P, { revision: made.data.revision, settings: { ...made.data.settings, testPath: '/auth/oauth' } });
    if (put.status !== 200) throw new Error(`setting the test path: ${put.status}`);
    const app = made.data.appId;

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      await page.context().route(`https://${stack.bank.host}/**`, async (route) => {
        const u = new URL(route.request().url());
        const response = await route.fetch({ url: `${stack.bank.url}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: stack.bank.host }, maxRedirects: 0, ignoreHTTPSErrors: true });
        await route.fulfill({ response });
      });
      await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(app)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('app-tab-settings').click({ timeout: 90_000 });
      const everyone = page.getByTestId('app-everyone');
      await everyone.waitFor({ timeout: 30_000 });
      const changed = page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/accounts\/[^/]+$/.test(r.url()), { timeout: 30_000 }).catch(() => undefined);
      await everyone.click();
      await changed;
      const own = page.getByTestId('app-connect-me');
      const offered = await own.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('7 Priya sets the MCP app to each person’s own account, and Connect my account is offered', offered, offered);

      const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 30_000 }), own.click()]);
      popup.on('pageerror', (e) => errors.push(`popup: ${e.message}`));
      const closed = await popup.waitForEvent('close', { timeout: 60_000 }).then(() => true, () => false);
      const mine = page.getByTestId('app-connected-as');
      const state = await page
        .waitForFunction(() => /Connected\b.* as /.test(document.querySelector('[data-testid=app-connected-as]')?.textContent ?? ''), null, { timeout: 30_000 })
        .then(async () => (await mine.innerText()).replace(/\s+/g, ' '), async () => (await mine.innerText().catch(() => '')).replace(/\s+/g, ' '));
      check('7 she signs in once through the pop-up, and her row says whom she is connected as', closed && /Connected\b.* as /.test(state), { closed, state });

      const t = await testTeamAccount(page, consoleUrl, { appId: app }, { own: true });
      check('8 Test works with her own account, answered 200', t.status === 'ok' && /\b200\b/.test(t.said) && /your own account/.test(t.said), t.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
