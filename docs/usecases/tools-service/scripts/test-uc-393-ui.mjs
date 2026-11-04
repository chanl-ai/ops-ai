// uc-393 a tool signs in with an OAuth client ID and secret, ui layer:
// docs/usecases/tools-service/connections-client-credentials.md. Priya, an Operations admin, presses Test on a
// client-credentials app page's Keys row: the gateway fetches a token and the read works, and neither the secret nor
// the token shows; a secret the bank refuses tests Failed and says invalid_client. Apps are set up through the API
// (connection_ui.mjs).
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, allowBank, connection, testTeamAccount } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);

await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const P = await as(PRIYA);
    const base = `https://${stack.bank.host}`;
    const client = (clientSecret) => ({ settings: { tokenUrl: `${base}/oauth2/token`, clientId: 'ops-gateway', scopes: 'accounts.read' }, secretValues: { clientSecret } });
    const at = { baseUrl: base, testPath: '/auth/oauth' };
    const right = await connection(P, `uc393 client ${RUN}`, 'oauth2_client_credentials', { live: client('cc-secret') }, at);
    const wrong = await connection(P, `uc393 wrong ${RUN}`, 'oauth2_client_credentials', { live: client('not-the-secret') }, at);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const r = await testTeamAccount(page, consoleUrl, right);
      check('7 the account fetches a token and tests Working with the team account, answered 200', r.status === 'ok' && /\b200\b/.test(r.said) && /team account/.test(r.said), r.said);
      check('7 the client secret does not show on its page', !r.page.includes('cc-secret'), r.page.slice(0, 300));
      const w = await testTeamAccount(page, consoleUrl, wrong);
      check('8 a secret the bank refuses tests Failed and says invalid_client', w.status !== 'ok' && /Failed/.test(w.said) && /invalid_client/.test(w.said), w.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
