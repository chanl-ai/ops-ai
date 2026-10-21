// uc-213 a workspace proves its email domain by DNS before it routes sign-in, ui layer. Headless Chromium against a
// console signed in through platform-service (dev seed) with the local fake identity provider and its DNS: Wanjiru
// (workspace admin, Security admin in every team) adds an OIDC provider on Settings > Sign-in, sees the domain pending
// with its TXT record, fails a verify, publishes the record and verifies; James (builder) is told the Security team sets it.
import { randomBytes } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { IDP_PORT, PLATFORM_PORT, ROOT, SIGNIN_SECRET, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SHOTS = join(ROOT, '.codeloop/evidence/195');
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const zone = `${randomBytes(4).toString('hex')}.harborpine.test`;
const CERT = `-----BEGIN CERTIFICATE-----${'A'.repeat(120)}-----END CERTIFICATE-----`;

async function signIn(page, consoleUrl, email) {
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
}
const ssoOf = async (email) => (await (await fetch(`${platform}/v1/auth/options`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) })).json()).data?.sso ?? null;
const shown = (locator, ms = 30_000) => locator.waitFor({ timeout: ms }).then(() => true, () => false);

async function pick(page, label, option) {
  await page.getByLabel(label).click();
  await page.getByRole('option', { name: option }).click();
}

await withUiStack(
  async (consoleUrl, stack) => {
    // Passwords stay on for everyone outside the SSO domain, so James can still sign in once SSO is set.
    const token = (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'w.kamau@harborpine.example', password: 'northfield-demo' }) })).json()).data?.token;
    const password = await fetch(`${platform}/v1/settings/sign-in/providers/password`, { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_security' }, body: JSON.stringify({ kind: 'password', label: 'Password' }) });
    check('Wanjiru keeps passwords on through the API', password.ok, password.status);
    const browser = await chromium.launch();
    try {
      mkdirSync(SHOTS, { recursive: true });
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await signIn(page, consoleUrl, 'w.kamau@harborpine.example');
      await page.goto(`${consoleUrl}/settings/security/sign-in`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      check('Settings > Sign-in lists the providers from platform-service', await shown(page.getByTestId('sign-in-providers'), 90_000));

      // A refusal the form cannot catch: a certificate that is not one, in the server's words under the field.
      await page.getByTestId('add-provider').click();
      await pick(page, 'Type', 'SAML 2.0');
      await page.getByLabel('Name', { exact: true }).fill('Broken SAML');
      await page.getByLabel('Identity provider entity ID').fill('urn:broken');
      await page.getByLabel('Sign-in URL').fill(`${stack.idpUrl}/saml/broken/sso`);
      await page.getByLabel('Signing certificate').fill(CERT);
      await page.getByTestId('provider-submit').click();
      check('a certificate platform refuses shows its reason under the field', await shown(page.getByText('The certificate is not a PEM X.509 certificate.')));
      await page.getByRole('button', { name: 'Cancel' }).click();

      await page.getByTestId('add-provider').click();
      await page.getByLabel('Name', { exact: true }).fill('Harbor & Pine SSO');
      await page.getByLabel('Issuer URL').fill(`${stack.idpUrl}/oidc/northfield`);
      await page.getByLabel('Client ID').fill('ops-console');
      await pick(page, 'Client secret', SIGNIN_SECRET);
      await page.locator('input#provider-domains').fill(zone);
      await page.locator('input#provider-domains').press('Enter');
      await pick(page, 'New people join as', 'Chat user');
      await page.getByTestId('provider-submit').click();
      const row = page.getByTestId('sign-in-providers').getByRole('row', { name: /Harbor & Pine SSO/ });
      check('the OIDC provider is saved and listed with its domain pending', (await shown(row)) && (await row.innerText()).includes(`${zone} (pending)`), await row.innerText().catch(() => ''));
      const domain = page.getByTestId(`domain-${zone}`);
      const value = await domain.getByRole('textbox').inputValue().catch(() => '');
      check('the domain shows the TXT record to publish', value.startsWith('ops-ai-verify='), value);
      check('the pending domain sends nobody to the provider', (await ssoOf(`teller@${zone}`)) === null);
      await page.screenshot({ path: join(SHOTS, 'uc-213-pending.png'), fullPage: true });

      await page.getByTestId(`verify-${zone}`).click();
      check('Verify with nothing published says what DNS held', await shown(page.getByText(/No TXT record ops-ai-verify=/)));
      const put = await fetch(`http://127.0.0.1:${IDP_PORT}/dns/txt/${zone}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ values: [value] }) });
      await page.getByTestId(`verify-${zone}`).click();
      const verified = await shown(domain.getByText('Verified'));
      check('after the record is published, Verify marks the domain verified', put.ok && verified);
      check('the verified domain now signs in through Harbor & Pine SSO', (await ssoOf(`teller@${zone}`))?.label === 'Harbor & Pine SSO');

      await page.reload({ waitUntil: 'domcontentloaded' });
      check('after a reload the provider and its verified domain are still there', (await shown(page.getByTestId(`domain-${zone}`).getByText('Verified'), 60_000)) && (await page.getByTestId(`verify-${zone}`).count()) === 0);
      check('MFA, sessions and sign-up show below as sample data', await shown(page.getByTestId('sample-data-notice')));
      await page.screenshot({ path: join(SHOTS, 'uc-213-verified.png'), fullPage: true });
      await page.setViewportSize({ width: 400, height: 860 });
      const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      check('the Sign-in page fits 400 px with no page scroll', !wide);
      check('no page errors', errors.length === 0, errors);

      const james = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
      await signIn(james, consoleUrl, 'j.richardson@harborpine.example');
      await james.goto(`${consoleUrl}/settings/security/sign-in`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      check('James is told the Security team sets sign-in, with no Add provider', (await shown(james.getByTestId('sign-in-no-access'), 60_000)) && (await james.getByTestId('add-provider').count()) === 0);
    } finally {
      await browser.close();
    }
  },
  { platform: true, signIn: true },
);
finish();
