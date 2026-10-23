// uc-161 an OIDC sign-in creates a chat-only person once, ui layer. Headless Chromium against a console signed in
// through platform-service, with the local fake identity provider standing in for the bank's: the sign-in page asks
// how the typed email signs in and offers what its workspace allows, and Continue with SSO goes there and back.
import { randomBytes } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, SIGNIN_SECRET, check, chromium, evidenceDir, finish, proveDomains, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const zone = `${randomBytes(4).toString('hex')}.harborpine.test`;
const TELLER = `new.teller@${zone}`;
const SHOTS = evidenceDir('188');

async function call(method, path, body, token, team) {
  const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(team ? { 'X-Team-Id': team } : {}) };
  const r = await fetch(`${platform}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json().catch(() => null) };
}
const signIn = async (email) => (await call('POST', '/v1/auth/sign-in', { email, password: 'northfield-demo' })).body?.data?.token;

await withUiStack(
  async (consoleUrl, stack) => {
    // Setup through the API, each status checked: Sam (Security admin) joins team_ops as admin, then sets the provider.
    const priya = await signIn('p.shah@harborpine.example');
    let sam = await signIn('s.adeyemi@harborpine.example');
    const invited = await call('POST', '/v1/settings/members/invite', { emails: ['s.adeyemi@harborpine.example'], role: 'admin' }, priya, 'team_ops');
    const token = invited.body?.data?.invites?.[0]?.token;
    const accepted = await call('POST', `/v1/invites/${token}/accept`, { name: 'Sam Adeyemi' }, sam);
    check('Sam joins team_ops as admin through an invitation he accepts', invited.status === 200 && accepted.status === 200, { invited: invited.status, accepted: accepted.status });
    sam = await signIn('s.adeyemi@harborpine.example');
    const oidc = await call('PUT', '/v1/settings/sign-in/providers/oidc-northfield', {
      kind: 'oidc',
      label: 'Harbor & Pine SSO',
      domains: [zone],
      oidc: { issuer: `${stack.idpUrl}/oidc/northfield`, clientId: 'ops-console', clientSecretRef: SIGNIN_SECRET },
      jit: { team: 'team_ops', role: 'chat_user' },
    }, sam, 'team_security');
    if (oidc.status === 200) await proveDomains(oidc.body.data, { Authorization: `Bearer ${sam}`, 'X-Team-Id': 'team_security' });
    const password = await call('PUT', '/v1/settings/sign-in/providers/password', { kind: 'password', label: 'Password' }, sam, 'team_security');
    check('Sam sets the OIDC provider for the domain and keeps passwords on', oidc.status === 200 && password.status === 200, { oidc: oidc.body, password: password.status });

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const form = page.getByTestId('login-form');
      await form.waitFor({ timeout: 120_000 });

      // Non-vacuous half: an email whose domain has no provider keeps the password form.
      await page.getByLabel('Work email').fill('j.richardson@harborpine.example');
      await page.waitForResponse((r) => r.url() === `${platform}/v1/auth/options`, { timeout: 30_000 });
      await page.waitForTimeout(300);
      check('an email with no SSO domain shows the password form', (await form.getAttribute('data-mode')) === 'password' && (await page.getByLabel('Password').count()) === 1);

      await page.getByLabel('Work email').fill(TELLER);
      await page.getByTestId('login-sso-notice').waitFor({ timeout: 30_000 }).catch(() => undefined);
      const notice = (await page.getByTestId('login-sso-notice').innerText().catch(() => '')).trim();
      check('the teller’s email turns the form into Continue with SSO, naming the provider', (await form.getAttribute('data-mode')) === 'sso' && notice.includes('Harbor & Pine SSO') && (await page.getByLabel('Password').count()) === 0, notice);
      mkdirSync(SHOTS, { recursive: true });
      await page.screenshot({ path: join(SHOTS, 'uc-161-login-sso.png') });

      // Continue: to the fake provider (which signs in the login_hint at once), back through platform-service to /sso/callback.
      const seen = [];
      page.on('request', (r) => r.isNavigationRequest() && seen.push(new URL(r.url()).origin + new URL(r.url()).pathname));
      await page.getByTestId('login-submit').click();
      const home = await page.waitForURL((u) => u.origin === consoleUrl && !u.pathname.startsWith('/login') && !u.pathname.startsWith('/sso'), { timeout: 120_000 }).then(() => true, () => false);
      const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('ops-platform-session') ?? 'null'));
      check('the round trip went to the provider, platform-service and the console callback', seen.some((u) => u.endsWith('/oidc/northfield/authorize')) && seen.some((u) => u === `${platform}/v1/auth/oidc/callback`) && seen.some((u) => u.endsWith('/sso/callback')), seen);
      check('the teller lands signed in as a chat user on team_ops through OIDC', home && stored?.principal?.email === TELLER && stored?.principal?.authMethod === 'oidc' && stored?.principal?.roles?.team_ops === 'chat_user', stored?.principal ?? page.url());
      check('no page errors', errors.length === 0, errors);
      await page.screenshot({ path: join(SHOTS, 'uc-161-signed-in.png') });
    } finally {
      await browser.close();
    }
  },
  { platform: true, signIn: true },
);
finish();
