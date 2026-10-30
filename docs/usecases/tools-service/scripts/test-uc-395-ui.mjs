// uc-395 a tool presents a client certificate from its connection, ui layer:
// docs/usecases/tools-service/connections-certificate.md. Priya, an Operations admin, presses Test the team account on a
// connection holding a client certificate for the bank stand-in's certificate-only listener, and it works. The ui
// harness's bank hands back no certificate-only host or client certificate (c-580), so this walk fails at step 5 until
// it does.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { readFileSync } from 'node:fs';
import { CONNECTION_STACK, allowBank, connection, testTeamAccount } from '../../lib/connection_ui.mjs';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 6);

await withUiStack(
  async (consoleUrl, stack) => {
    const { mtlsHost, mtls } = stack.bank;
    check('5 the stack serves the certificate-only listener and hands back its client certificate (c-580)', Boolean(mtlsHost && mtls), { keys: Object.keys(stack.bank) });
    if (!mtlsHost || !mtls) return;
    await allowBank(stack.bank);
    const pem = Object.fromEntries(Object.entries(mtls).map(([k, v]) => [k, readFileSync(v, 'utf8')]));
    const P = await as(PRIYA);
    const environment = { settings: { clientCertificate: pem.client_cert, trustedCa: pem.ca }, secretValues: { clientKey: pem.client_key } };
    const conn = await connection(P, `uc395 certificate ${RUN}`, 'none', { production: environment }, { baseUrl: `https://${mtlsHost}`, testPath: '/auth/mtls' });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const t = await testTeamAccount(page, consoleUrl, conn.id);
      check('5 Test the team account presents the certificate and works, answered 200; the key never shows', t.status === 'ok' && /\b200\b/.test(t.said) && !t.page.includes('PRIVATE KEY'), t.said);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
