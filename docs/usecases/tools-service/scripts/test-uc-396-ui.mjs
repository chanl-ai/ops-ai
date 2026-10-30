// uc-396 a builder adds an MCP server behind OAuth by its address and signs in once, ui layer:
// docs/usecases/tools-service/mcp-sign-in.md. The server is added by its address through the API (the console's connect
// dialog runs on the mock only). Priya, an Operations admin, opens its connection page, sets it to each person's own
// account, connects hers through the pop-up, and Test connection works with her account; People connected lists her.
// The browser reaches the bank stand-in's sign-in host on its own address, as tools-service does by its name map.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, tools } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);
const send = async (method, path, headers, body) => {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await as(PRIYA);
    const server = `https://${stack.bank.host}/mcp/screening`;
    const made = await send('POST', '/v1/connections/mcp', P, { serverUrl: server, name: `uc396 screening ${RUN}` });
    if (made.status !== 201) throw new Error(`adding the MCP server: ${made.status}`);
    // Test connection reads a path on the server's host with the connection's token; the stand-in's /auth/oauth says
    // which client the token is for.
    const test = made.data.environments.test;
    const put = await send('PUT', `/v1/connections/${made.data.id}/environments/test`, P, { revision: made.data.revision, settings: { ...test.settings, testPath: '/auth/oauth' } });
    if (put.status !== 200) throw new Error(`setting the test path: ${put.status}`);
    const id = made.data.id;

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      await page.context().route(`https://${stack.bank.host}/**`, async (route) => {
        const u = new URL(route.request().url());
        const response = await route.fetch({ url: `${stack.bank.url}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: stack.bank.host }, maxRedirects: 0, ignoreHTTPSErrors: true });
        await route.fulfill({ response });
      });
      await page.goto(`${consoleUrl}/tools/connections/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('sign-in-setting').waitFor({ timeout: 90_000 });
      await page.locator('label[for=sign-in-person]').click();
      await page.getByTestId('sign-in-save').click();
      const own = page.getByTestId('connect-own');
      const offered = await own.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('7 Priya sets the MCP connection to each person’s own account, and Connect your account is offered', offered, offered);

      const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 30_000 }), own.click()]);
      popup.on('pageerror', (e) => errors.push(`popup: ${e.message}`));
      const closed = await popup.waitForEvent('close', { timeout: 60_000 }).then(() => true, () => false);
      const listed = page.getByTestId('people-connected');
      const people = await listed.waitFor({ timeout: 30_000 }).then(async () => (await listed.innerText()).replace(/\s+/g, ' '), () => '');
      check('7 she signs in once through the pop-up, and People connected lists her', closed && /Connected/.test(people), { closed, people });

      const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/test$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
      await page.getByTestId('test-own').click();
      await answered;
      const health = page.getByTestId('health');
      await health.waitFor({ timeout: 60_000 });
      const said = (await health.innerText()).replace(/\s+/g, ' ');
      check('8 Test connection works with her own account, answered 200', (await health.getAttribute('data-status')) === 'ok' && /\b200\b/.test(said) && /your own account/.test(said), said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
