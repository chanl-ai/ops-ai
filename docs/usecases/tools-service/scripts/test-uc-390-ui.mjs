// uc-390 a tool signs in with an API key from its connection, ui layer: docs/usecases/tools-service/connections-api-key.md.
// Priya, an Operations admin, opens three API-key connections on their pages and presses Test the team account: the
// header key works in production, the query key in test, and a wrong production key fails with the bank's 401. No key
// shows on any page. Connections are set up through the API (connection_ui.mjs); the bank stand-in answers on https.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, connection, testTeamAccount } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const TEST_KEY = 'test-bank-key';
const PROD_KEY = 'prod-bank-key';
const RUN = Math.random().toString(36).slice(2, 6);
const keyed = (name, key) => ({ settings: { name }, secretValues: { key } });

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await as(PRIYA);
    const at = { baseUrl: `https://${stack.bank.host}`, testPath: '/auth/api-key' };
    const header = await connection(P, `uc390 header ${RUN}`, 'api_key', { test: keyed('X-Api-Key', TEST_KEY), production: keyed('X-Api-Key', PROD_KEY) }, at);
    const query = await connection(P, `uc390 query ${RUN}`, 'api_key', { test: { settings: { placement: 'query', name: 'api_key' }, secretValues: { key: TEST_KEY } } }, at);
    const wrong = await connection(P, `uc390 wrong ${RUN}`, 'api_key', { production: keyed('X-Api-Key', 'not-the-bank-key') }, at);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const h = await testTeamAccount(page, consoleUrl, header.id);
      check('5 the header key connection tests Working in production, answered 200', h.status === 'ok' && /\b200\b/.test(h.said) && /production/.test(h.said), h.said);
      check('5 neither key shows on its page', !h.page.includes(TEST_KEY) && !h.page.includes(PROD_KEY), h.page.slice(0, 300));

      const q = await testTeamAccount(page, consoleUrl, query.id);
      check('6 the query key connection, set for test only, tests Working in test', q.status === 'ok' && /\b200\b/.test(q.said) && /\btest\b/.test(q.said), q.said);

      const w = await testTeamAccount(page, consoleUrl, wrong.id);
      check("7 a wrong production key tests Failed with the bank's 401", w.status !== 'ok' && /Failed/.test(w.said) && /\b401\b/.test(w.said), w.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
