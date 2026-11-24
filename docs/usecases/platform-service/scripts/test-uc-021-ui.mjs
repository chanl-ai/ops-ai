// uc-021 sign in, session, refresh, sign out, ui layer. Headless Chromium against a console signed in through
// platform-service (dev seed: James Richardson, builder on team_ops), whose registry calls go to the agents service.
import { randomBytes } from 'node:crypto';

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, SIGNIN_SECRET, check, chromium, expectSampleData, finish, proveDomains, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const EMAIL = 'j.richardson@harborpine.example';
const KEY = 'ops-platform-session';
const stored = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) ?? 'null'), KEY);

await withUiStack(
  async (consoleUrl, stack) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
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
      // A reload checks the session first and signs a rejected token out, so the token is spoiled mid-session instead:
      // another tab writes it, and this page adopts it from the storage event, as it adopts another tab's refresh.
      registryStatus.length = 0;
      registryAuth.length = 0;
      let refreshCount = 0;
      page.on('request', (r) => r.url() === `${platform}/v1/auth/refresh` && refreshCount++);
      const other = await page.context().newPage();
      await other.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await other.getByTestId('page-title').first().waitFor({ timeout: 60_000 });
      await other.evaluate((k) => {
        const v = JSON.parse(localStorage.getItem(k));
        v.token = `${v.token.slice(0, -6)}AAAAAA`;
        localStorage.setItem(k, JSON.stringify(v));
      }, KEY);
      await other.close();
      const renewed = page.waitForResponse((r) => r.url() === `${platform}/v1/auth/refresh`, { timeout: 60_000 });
      await page.getByRole('link', { name: 'Workflows' }).first().click();
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
        const v = JSON.parse(localStorage.getItem(k));
        v.expiresAt = new Date(Date.now() + 5_000).toISOString();
        localStorage.setItem(k, JSON.stringify(v));
      }, KEY);
      const refreshed = page.waitForResponse((r) => r.url() === `${platform}/v1/auth/refresh`, { timeout: 60_000 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      const refreshRes = await refreshed.catch(() => undefined);
      // The new tokens are written after the refresh answers; wait for them rather than read in between.
      let second = await stored(page);
      for (let i = 0; i < 40 && second?.refreshToken === first.refreshToken; i++) second = (await page.waitForTimeout(250), await stored(page));
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

      // A person in two teams lands in their own one: the switcher and the calls both name Operations, not the
      // console's default (Platform). Wanjiru invites James to Platform and he accepts; then he signs in afresh.
      const tokenOf = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data;
      const wanjiru = await tokenOf('w.kamau@harborpine.example');
      const invited = await (await fetch(`${platform}/v1/settings/members/invite`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${wanjiru.token}`, 'X-Team-Id': 'team_platform' }, body: JSON.stringify({ emails: [EMAIL], role: 'viewer' }) })).json();
      const inviteToken = invited.data?.invites?.[0]?.token;
      const james = await tokenOf(EMAIL);
      const accepted = await fetch(`${platform}/v1/invites/${inviteToken}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${james.token}` }, body: JSON.stringify({ name: 'James Richardson' }) });
      const two = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      two.on('pageerror', (e) => errors.push(e.message));
      const twoTeams = [];
      two.on('request', (r) => isRegistry(r) && twoTeams.push(r.headers()['x-team-id'] ?? null));
      await two.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await two.getByLabel('Email').fill(EMAIL);
      await two.getByLabel('Password').fill('northfield-demo');
      await two.getByRole('button', { name: /^Sign in/ }).first().click();
      await two.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await two.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const twoSwitcher = two.getByRole('button', { name: /^Team: (?!loading).*\. Switch team$/ });
      await twoSwitcher.first().waitFor({ timeout: 30_000 });
      await two.waitForTimeout(1_000);
      const twoActive = await twoSwitcher.first().getAttribute('aria-label');
      await twoSwitcher.first().click();
      const twoItems = (await two.getByRole('menuitem').allInnerTexts()).map((t) => t.split('\n')[0].trim());
      await two.keyboard.press('Escape');
      check(
        'in two teams, James lands in his own (Operations) on the switcher and on every call',
        accepted.status === 200 && twoItems.includes('Platform') && twoActive === 'Team: Operations. Switch team' && twoTeams.length > 0 && twoTeams.every((t) => t === 'team_ops'),
        { invite: invited.success, accepted: accepted.status, twoItems, twoActive, teams: [...new Set(twoTeams)] },
      );

      // A workspace that moves to company sign-in leaves two kinds of member who cannot sign in: a person with no
      // password and no link, who gets a mailed link invite, and an admin in that state, who may not (an invite link
      // never opens an admin's account) and links from their own session instead. The members list marks both, and
      // Resend invites mails the first only, never showing a link.
      const zone = `${randomBytes(4).toString('hex')}.harborpine.test`;
      const json = { 'Content-Type': 'application/json' };
      const call = async (method, path, body, token, team) => {
        const r = await fetch(`${platform}${path}`, { method, headers: { ...json, ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(team ? { 'X-Team-Id': team } : {}) }, body: body ? JSON.stringify(body) : undefined });
        return { status: r.status, body: await r.json().catch(() => null) };
      };
      const signedIn = async (email) => (await call('POST', '/v1/auth/sign-in', { email, password: 'northfield-demo' })).body?.data;
      const priya = await signedIn('p.shah@harborpine.example');
      let sam = (await signedIn('s.adeyemi@harborpine.example'))?.token;
      const made = {};
      for (const [who, role] of [['lost', 'builder'], ['boss', 'admin']]) {
        const email = `${who}@${zone}`;
        const inv = await call('POST', '/v1/settings/members/invite', { emails: [email], role }, priya.token, 'team_ops');
        const acc = await call('POST', `/v1/invites/${inv.body?.data?.invites?.[0]?.token}/accept`, { name: `${who} person` });
        made[who] = inv.status === 200 && acc.status === 200;
      }
      const samInvite = await call('POST', '/v1/settings/members/invite', { emails: ['s.adeyemi@harborpine.example'], role: 'admin' }, priya.token, 'team_ops');
      const samAccepted = await call('POST', `/v1/invites/${samInvite.body?.data?.invites?.[0]?.token}/accept`, { name: 'Sam Adeyemi' }, sam);
      sam = (await signedIn('s.adeyemi@harborpine.example'))?.token;
      const oidc = await call('PUT', '/v1/settings/sign-in/providers/oidc-northfield', {
        kind: 'oidc',
        label: 'Harbor & Pine SSO',
        domains: [zone],
        oidc: { issuer: `${stack.idpUrl}/oidc/northfield`, clientId: 'ops-console', clientSecretRef: SIGNIN_SECRET },
        jit: { team: 'team_ops', role: 'chat_user' },
      }, sam, 'team_security');
      if (oidc.status === 200) await proveDomains(oidc.body.data, { Authorization: `Bearer ${sam}`, 'X-Team-Id': 'team_security' });
      const roster = await call('GET', '/v1/settings/members?pageSize=100', undefined, priya.token, 'team_ops');
      const rows = roster.body?.data?.data ?? [];
      const lost = rows.find((m) => m.email === `lost@${zone}`);
      const boss = rows.find((m) => m.email === `boss@${zone}`);
      check('the setup leaves one builder and one admin with no password or link, in a company-sign-in workspace', made.lost && made.boss && samAccepted.status === 200 && oidc.status === 200 && lost?.needsInvite === true && boss?.linksOwnSession === true, { made, sam: samAccepted.status, oidc: oidc.status, lost, boss });

      expectSampleData('/settings/members');
      const admin = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      admin.on('pageerror', (e) => errors.push(e.message));
      await admin.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await admin.evaluate(([k, issued]) => localStorage.setItem(k, JSON.stringify({ ...issued, issuedAt: new Date().toISOString() })), [KEY, priya]);
      await admin.goto(`${consoleUrl}/settings/members`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await admin.getByTestId(`member-needs-invite-${lost?.id}`).waitFor({ timeout: 60_000 }).catch(() => undefined);
      check('the members list marks the builder "Needs a new invite" and the admin "Link from your own session…"', (await admin.getByTestId(`member-needs-invite-${lost?.id}`).innerText().catch(() => '')).includes('Needs a new invite') && (await admin.getByTestId(`member-links-own-${boss?.id}`).innerText().catch(() => '')).includes('Link from your own session') && (await admin.getByTestId(`member-needs-invite-${boss?.id}`).count()) === 0);

      await admin.getByTestId('reinvite-affected').click();
      const reinvited = admin.waitForResponse((r) => r.url().endsWith('/v1/settings/members/reinvite'), { timeout: 30_000 });
      await admin.getByRole('dialog').getByRole('button', { name: 'Send' }).click();
      const reinvite = await (await reinvited).json().catch(() => null);
      await admin.waitForTimeout(500);
      const mailed = readdirSync(stack.mailDir).filter((f) => f.endsWith('.json')).map((f) => JSON.parse(readFileSync(join(stack.mailDir, f), 'utf8')));
      const toLost = mailed.filter((m) => (m.to ?? []).includes(`lost@${zone}`) && /\/invite\//.test(m.body ?? ''));
      const toBoss = mailed.filter((m) => (m.to ?? []).includes(`boss@${zone}`));
      check(
        'Resend invites mails the builder’s own address only: no link in the answer or on the page, nothing to the admin',
        reinvite?.data?.mailed?.some((m) => m.email === `lost@${zone}`) && reinvite?.data?.skipped?.some((s) => s.reason === 'links_own_session') && !JSON.stringify(reinvite).includes('/invite/') && toLost.length === 1 && toBoss.length === 0 && !(await admin.locator('body').innerText()).includes('/invite/'),
        { reinvite: reinvite?.data, toLost: toLost.length, toBoss: toBoss.length },
      );

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, signIn: true },
);

finish();
