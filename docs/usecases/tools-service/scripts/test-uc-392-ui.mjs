// uc-392 a tool signs in with a bearer token from its connection, ui layer: docs/usecases/tools-service/connections-bearer.md.
// Priya, an Operations admin, presses Test the team account on a bearer connection's page: the production token works
// and never shows; a token the bank does not know fails with its 401. Connections are set up through the API
// (connection_ui.mjs).
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, connection, testTeamAccount } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);
const bearer = (token) => ({ secretValues: { token } });

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await as(PRIYA);
    const at = { baseUrl: `https://${stack.bank.host}`, testPath: '/auth/bearer' };
    const right = await connection(P, `uc392 bearer ${RUN}`, 'bearer', { test: bearer('test-bearer-token'), production: bearer('prod-bearer-token') }, at);
    const wrong = await connection(P, `uc392 wrong ${RUN}`, 'bearer', { production: bearer('not-the-token') }, at);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const r = await testTeamAccount(page, consoleUrl, right.id);
      check('4 the connection tests Working in production, answered 200', r.status === 'ok' && /\b200\b/.test(r.said) && /production/.test(r.said), r.said);
      check('4 neither token shows on its page', !r.page.includes('test-bearer-token') && !r.page.includes('prod-bearer-token'), r.page.slice(0, 300));
      const w = await testTeamAccount(page, consoleUrl, wrong.id);
      check("5 a token the bank does not know tests Failed with the bank's 401", w.status !== 'ok' && /Failed/.test(w.said) && /\b401\b/.test(w.said), w.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
