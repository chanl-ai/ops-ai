// uc-394 a person signs a connection in once with the team's account, ui layer:
// docs/usecases/tools-service/connections-sign-in.md. Priya, an Operations admin, opens a team-account OAuth connection
// on its page, signs the team account in once with Connect the team account, and Test the team account works with it.
// The connection is set up through the API.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, connection, testTeamAccount } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await as(PRIYA);
    const base = `https://${stack.bank.host}`;
    const settings = { authorizeUrl: `${base}/oauth2/authorize`, tokenUrl: `${base}/oauth2/token`, clientId: 'ops-console', scopes: 'crm.read' };
    const conn = await connection(P, `uc394 crm ${RUN}`, 'oauth2_auth_code', { test: { settings, secretValues: { clientSecret: 'ac-secret' } } }, { baseUrl: base, testPath: '/auth/oauth' });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      await page.context().route(`${base}/**`, async (route) => {
        const u = new URL(route.request().url());
        const response = await route.fetch({ url: `${stack.bank.url}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: stack.bank.host }, maxRedirects: 0, ignoreHTTPSErrors: true });
        await route.fulfill({ response });
      });
      await page.goto(`${consoleUrl}/tools/connections/${conn.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('test-team').waitFor({ timeout: 90_000 });
      const signIn = page.getByRole('button', { name: /(connect|sign in).*team account/i });
      const offered = (await signIn.count()) > 0;
      let closed = false;
      if (offered) {
        const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 30_000 }), signIn.first().click()]);
        closed = await popup.waitForEvent('close', { timeout: 60_000 }).then(() => true, () => false);
      }
      const buttons = (await page.locator('main button').allInnerTexts()).map((b) => b.trim()).filter(Boolean);
      check('6 Priya signs the team account in once from the connection page', offered && closed, { offered, closed, buttons });

      const t = await testTeamAccount(page, consoleUrl, conn.id);
      check('7 Test the team account works with the signed-in account, answered 200', t.status === 'ok' && /\b200\b/.test(t.said), t.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
