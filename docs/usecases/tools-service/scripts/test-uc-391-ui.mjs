// uc-391 a tool signs in with a username and password from its connection, ui layer:
// docs/usecases/tools-service/connections-basic.md. Priya, an Operations admin, presses Test the team account on a
// basic-auth connection's page: the production user works and the password never shows; a wrong production password
// fails with the bank's 401. Connections are set up through the API (connection_ui.mjs).
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, connection, testTeamAccount } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);
const user = (username, password) => ({ settings: { username }, secretValues: { password } });

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await as(PRIYA);
    const at = { baseUrl: `https://${stack.bank.host}`, testPath: '/auth/basic' };
    const right = await connection(P, `uc391 basic ${RUN}`, 'basic', { test: user('ops-test', 'test-pass'), production: user('ops-prod', 'prod-pass') }, at);
    const wrong = await connection(P, `uc391 wrong ${RUN}`, 'basic', { production: user('ops-prod', 'not-the-password') }, at);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const r = await testTeamAccount(page, consoleUrl, right.id);
      check('5 the connection tests Working in production, answered 200', r.status === 'ok' && /\b200\b/.test(r.said) && /production/.test(r.said), r.said);
      check('5 neither password shows on its page', !r.page.includes('test-pass') && !r.page.includes('prod-pass'), r.page.slice(0, 300));
      const w = await testTeamAccount(page, consoleUrl, wrong.id);
      check("6 a wrong production password tests Failed with the bank's 401", w.status !== 'ok' && /Failed/.test(w.said) && /\b401\b/.test(w.said), w.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
