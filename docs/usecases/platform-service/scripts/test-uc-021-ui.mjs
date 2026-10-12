// uc-021 sign in, session, refresh, sign out, ui layer. Headless Chromium against a console signed in through
// platform-service (dev seed: James Richardson, builder on team_ops), whose registry calls go to the agents service.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const EMAIL = 'j.richardson@northfieldbank.com';
const KEY = 'ops-platform-session';
const stored = (page) => page.evaluate((k) => JSON.parse(sessionStorage.getItem(k) ?? 'null'), KEY);

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const registryAuth = [];
      const registryStatus = [];
      const isRegistry = (r) => r.url().startsWith(`http://127.0.0.1:${AGENTS_PORT}/v1/`) && r.method() !== 'OPTIONS';
      const registryTeams = [];
      page.on('request', (r) => isRegistry(r) && (registryAuth.push(r.headers().authorization ?? null), registryTeams.push(r.headers()['x-team-id'] ?? null)));
      // A call the agents service's CORS refuses never gets a response; counting answers catches that.
      page.on('response', (r) => isRegistry(r.request()) && registryStatus.push(r.status()));

      // Non-vacuous half: a wrong password keeps the person on /login with no session stored.
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(EMAIL);
      await page.getByLabel('Password').fill('not-the-password');
      const refused = page.waitForResponse((r) => r.url() === `${platform}/v1/auth/sign-in`, { timeout: 60_000 });
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      check('a wrong password is refused and stays on /login with no session', (await refused).status() === 401 && page.url().includes('/login') && (await stored(page)) === null);

      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      const left = await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).then(() => true, () => false);
      const first = await stored(page);
      const claims = first ? JSON.parse(Buffer.from(first.token.split('.')[1], 'base64url').toString()) : {};
      check('the demo password signs James in as builder on team_ops with a 15-minute token', left && first?.principal?.roles?.team_ops === 'builder' && claims.exp - claims.iat === 900 && claims.aud?.includes('agents'), { left, roles: first?.principal?.roles, ttl: claims.exp - claims.iat });

      await page.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('page-title').first().waitFor({ timeout: 120_000 });
      for (let i = 0; i < 40 && registryStatus.length < registryAuth.length; i++) await page.waitForTimeout(250);
      check('registry calls carry his token and are answered', registryAuth.length > 0 && registryAuth.every((a) => a === `Bearer ${first?.token}`) && registryStatus.length === registryAuth.length && registryStatus.every((s) => s < 400), { calls: registryAuth.length, statuses: registryStatus });
      // The console's own team choice (team_platform by default) is outside his token; services would answer 403.
      check('registry calls name a team his token holds (team_ops)', registryTeams.length > 0 && registryTeams.every((t) => t === 'team_ops'), registryTeams);
      // The switcher lists his own teams from platform-service (one: Operations); teams are created in platform settings.
      const switcher = page.getByRole('button', { name: /^Team: (?!loading).*\. Switch team$/ });
      await switcher.first().waitFor({ timeout: 30_000 });
      const active = await switcher.first().getAttribute('aria-label');
      await switcher.first().click();
      const items = (await page.getByRole('menuitem').allInnerTexts()).map((t) => t.split('\n')[0].trim());
      await page.keyboard.press('Escape');
      check('the team switcher lists only his teams (Operations) and offers no Add team', active === 'Team: Operations. Switch team' && JSON.stringify(items) === '["Operations"]', { active, items });
      const menu = page.getByRole('button', { name: new RegExp(EMAIL.replace('.', '\\.')) });
      const named = await menu.first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('the user menu names the signed-in person', named && (await menu.first().innerText()).includes('James Richardson'));

      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('page-title').first().waitFor({ timeout: 60_000 });
      check('a reload keeps the session', !page.url().includes('/login') && (await stored(page))?.token === first?.token);

      // The agents service verifies tokens: no token is 401, and a token it rejects makes the console renew and retry.
      const bare = await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/agents?page=1&pageSize=5`);
      check('the agents service refuses a call with no token (401)', bare.status === 401, bare.status);
      await page.evaluate((k) => {
        const v = JSON.parse(sessionStorage.getItem(k));
        v.token = `${v.token.slice(0, -6)}AAAAAA`;
        sessionStorage.setItem(k, JSON.stringify(v));
      }, KEY);
      registryStatus.length = 0;
      registryAuth.length = 0;
      let refreshCount = 0;
      page.on('request', (r) => r.url() === `${platform}/v1/auth/refresh` && refreshCount++);
      const renewed = page.waitForResponse((r) => r.url() === `${platform}/v1/auth/refresh`, { timeout: 60_000 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      const renewRes = await renewed.catch(() => undefined);
      await page.getByTestId('page-title').first().waitFor({ timeout: 60_000 });
      for (let i = 0; i < 40 && registryStatus.filter((x) => x < 400).length === 0; i++) await page.waitForTimeout(250);
      check('a rejected token is renewed once and the call retried', renewRes?.status() === 200 && registryStatus.includes(401) && registryStatus.some((x) => x < 400) && !page.url().includes('/login'), { refresh: renewRes?.status(), statuses: registryStatus });
      await page.waitForLoadState('networkidle');
      const renewedSession = await stored(page);
      check('the rejected token was renewed exactly once', !!renewedSession && registryStatus.filter((x) => x === 401).length >= 1 && refreshCount === 1, { refreshes: refreshCount });
      first.token = renewedSession?.token ?? first.token;
      first.refreshToken = renewedSession?.refreshToken ?? first.refreshToken;

      // A token inside the refresh lead is renewed on load: both tokens rotate and the spent refresh token is refused.
      await page.evaluate((k) => {
        const v = JSON.parse(sessionStorage.getItem(k));
        v.expiresAt = new Date(Date.now() + 5_000).toISOString();
        sessionStorage.setItem(k, JSON.stringify(v));
      }, KEY);
      const refreshed = page.waitForResponse((r) => r.url() === `${platform}/v1/auth/refresh`, { timeout: 60_000 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      const refreshRes = await refreshed.catch(() => undefined);
      const second = await stored(page);
      check('near expiry the console refreshes both tokens', refreshRes?.status() === 200 && !!second && second.token !== first.token && second.refreshToken !== first.refreshToken, { status: refreshRes?.status(), same: second?.token === first.token, sameRefresh: second?.refreshToken === first.refreshToken });
      const reuse = await fetch(`${platform}/v1/auth/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refreshToken: first?.refreshToken }) });
      check('the spent refresh token is refused (401)', reuse.status === 401, reuse.status);

      // Reusing a refresh token ends the session on the issuer; sign in again for the sign-out half.
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded' });
      await page.getByLabel('Email').fill(EMAIL);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const third = await stored(page);
      await page.getByRole('button', { name: new RegExp(EMAIL.replace('.', '\\.')) }).first().click();
      const signedOut = page.waitForResponse((r) => r.url() === `${platform}/v1/auth/sign-out`, { timeout: 30_000 });
      await page.getByTestId('sign-out').click();
      const outRes = await signedOut;
      await page.waitForURL(/\/login/, { timeout: 30_000 }).catch(() => undefined);
      const after = await fetch(`${platform}/v1/auth/session`, { headers: { Authorization: `Bearer ${third?.token}` } });
      check('sign-out ends the session: /login, nothing stored, and the old token is refused', outRes.status() === 204 && page.url().includes('/login') && (await stored(page)) === null && after.status === 401, { signOut: outRes.status(), session: after.status });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
