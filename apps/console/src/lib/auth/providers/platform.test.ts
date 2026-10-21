import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AuthError } from '../provider.ts';
import { createPlatformProvider } from './platform.ts';

const principal = { kind: 'person', sub: 'usr_approver', email: 'm.okafor@harborpine.example', name: 'Maya Okafor', tenantId: 'local', teamId: 'team_ops', teamIds: ['team_ops'], roles: { team_ops: 'approver' }, scopes: [], authMethod: 'dev' };
const issued = { token: 'session-token', refreshToken: 'ses_1.secret', expiresAt: new Date(Date.now() + 900_000).toISOString(), principal };

/** A platform-service stand-in: records each request and answers sign-in and step-up the way the real one does. */
function platformFetch(stepUp: (body: { password: string }, auth: string | undefined) => Response) {
  const calls: { path: string; auth: string | undefined; body: unknown }[] = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace('http://platform', '');
    const headers = init?.headers as Record<string, string> | undefined;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ path, auth: headers?.Authorization, body });
    if (path === '/v1/auth/sign-in') return Response.json({ success: true, data: issued });
    if (path === '/v1/auth/step-up') return stepUp(body, headers?.Authorization);
    return Response.json({ success: false, error: { code: 'not_found', message: 'no such route' } }, { status: 404 });
  }) as typeof fetch;
  return calls;
}

test('reauthenticate sends the password under the session token and returns the step-up as the dialog expects it', async () => {
  const expiresAt = new Date(Date.now() + 300_000).toISOString();
  const calls = platformFetch(() => Response.json({ success: true, data: { token: 'step-up-token', expiresAt } }));
  const provider = createPlatformProvider('http://platform');
  await provider.signInWithPassword('m.okafor@harborpine.example', 'northfield-demo');
  const stepUp = await provider.reauthenticate({ method: 'password', password: 'northfield-demo' });
  assert.deepEqual(stepUp, { token: 'step-up-token', expiresAt });
  const call = calls.find((c) => c.path === '/v1/auth/step-up');
  assert.deepEqual(call, { path: '/v1/auth/step-up', auth: 'Bearer session-token', body: { password: 'northfield-demo' } });
});

test('a wrong password surfaces the service message as invalid credentials', async () => {
  platformFetch(() => Response.json({ success: false, error: { code: 'wrong_password', message: 'That password is not right.' } }, { status: 401 }));
  const provider = createPlatformProvider('http://platform');
  await provider.signInWithPassword('m.okafor@harborpine.example', 'northfield-demo');
  await assert.rejects(provider.reauthenticate({ method: 'password', password: 'nope' }), (e: unknown) => e instanceof AuthError && e.code === 'invalid_credentials' && e.message === 'That password is not right.');
});

test('reauthenticate with nobody signed in asks for a sign-in and calls nothing', async () => {
  const calls = platformFetch(() => Response.json({ success: true, data: { token: 'x', expiresAt: 'y' } }));
  const provider = createPlatformProvider('http://platform');
  await assert.rejects(provider.reauthenticate({ method: 'password', password: 'northfield-demo' }), (e: unknown) => e instanceof AuthError && e.code === 'no_session');
  assert.equal(calls.length, 0);
});

/** A browser's shared local storage, so a test can play two tabs that hold one session. */
function sharedStorage() {
  const data = new Map<string, string>();
  const localStorage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), removeItem: (k: string) => void data.delete(k) };
  (globalThis as { window?: unknown }).window = { localStorage, addEventListener: () => undefined };
  return data;
}
const expiring = () => ({ ...issued, expiresAt: new Date(Date.now() + 120_000).toISOString() });

test('a refresh that fails on the network keeps the session; only a 401 ends it', async () => {
  sharedStorage();
  let answer: () => Response | Promise<Response> = () => Response.json({ success: true, data: expiring() });
  globalThis.fetch = (async (url: string | URL | Request) => (String(url).endsWith('/v1/auth/refresh') ? answer() : Response.json({ success: true, data: expiring() }))) as typeof fetch;
  const provider = createPlatformProvider('http://platform');
  await provider.signInWithPassword('m.okafor@harborpine.example', 'northfield-demo');
  answer = () => Promise.reject(new TypeError('fetch failed'));
  assert.ok(await provider.renew(), 'offline: still signed in');
  answer = () => Response.json({ success: false, error: { code: 'service_unavailable', message: 'restarting' } }, { status: 503 });
  assert.ok(await provider.renew(), 'a 503 while the service restarts: still signed in');
  answer = () => Response.json({ success: false, error: { code: 'unauthenticated', message: 'Sign in again.' } }, { status: 401 });
  assert.equal(await provider.renew(), null, 'a 401: signed out');
  assert.equal(provider.identity(), null);
  delete (globalThis as { window?: unknown }).window;
});

test("a tab that refreshes after another already did takes the other's tokens and spends nothing", async () => {
  sharedStorage();
  const spent: string[] = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    if (String(url).endsWith('/v1/auth/refresh')) {
      const { refreshToken } = JSON.parse(String(init?.body));
      if (spent.includes(refreshToken)) return Response.json({ success: false, error: { code: 'unauthenticated', message: 'reused' } }, { status: 401 });
      spent.push(refreshToken);
      return Response.json({ success: true, data: { ...issued, token: `token-${spent.length}`, refreshToken: `ses_1.secret-${spent.length}` } });
    }
    return Response.json({ success: true, data: expiring() });
  }) as typeof fetch;
  const first = createPlatformProvider('http://platform');
  await first.signInWithPassword('m.okafor@harborpine.example', 'northfield-demo');
  const second = createPlatformProvider('http://platform');
  assert.equal(second.identity()?.token, 'session-token', 'a new tab is signed in from shared storage');
  assert.equal((await first.renew())?.token, 'token-1');
  // The second tab still remembers the old refresh token; renewing must adopt tab one's, not spend the old one again.
  assert.equal((await second.renew())?.token, 'token-1');
  assert.deepEqual(spent, ['ses_1.secret']);
  // Signing out clears each tab's refresh timer, so the test process can end.
  await first.signOut();
  await second.signOut();
  delete (globalThis as { window?: unknown }).window;
});

/** One tab: its own session storage beside the shared local storage. */
function tab() {
  const local = new Map<string, string>();
  const session = new Map<string, string>();
  const store = (m: Map<string, string>) => ({ getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) });
  (globalThis as { window?: unknown }).window = { localStorage: store(local), sessionStorage: store(session), addEventListener: () => undefined };
  return session;
}

test('SSO completes only in the tab that started it, with that tab’s flow key, and the session says sso', async () => {
  const session = tab();
  const sso = { ...issued, principal: { ...principal, authMethod: 'saml' } };
  const calls: { path: string; body: unknown }[] = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace('http://platform', '');
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ path, body });
    if (path === '/v1/auth/sso/start') return Response.json({ success: true, data: { redirectUrl: 'http://idp/sso?x=1', flowKey: 'flow-key-1' } });
    if (path === '/v1/auth/sso/complete') return Response.json({ success: true, data: sso });
    return Response.json({ success: false, error: { code: 'not_found', message: 'no' } }, { status: 404 });
  }) as typeof fetch;
  const provider = createPlatformProvider('http://platform');
  // A code that reaches a tab which never started a round trip is refused before any call.
  await assert.rejects(provider.completeSso('leaked-code'), (e: unknown) => e instanceof AuthError && e.code === 'invalid_token');
  assert.equal(calls.length, 0);
  const { redirectUrl } = await provider.startSso({ email: 'a@bank.test', next: '/reviews' });
  assert.equal(redirectUrl, 'http://idp/sso?x=1');
  assert.deepEqual(calls[0], { path: '/v1/auth/sso/start', body: { email: 'a@bank.test', next: '/reviews' } });
  const result = await provider.completeSso('code-1');
  assert.deepEqual(calls[1], { path: '/v1/auth/sso/complete', body: { code: 'code-1', flowKey: 'flow-key-1' } });
  assert.equal(result.status === 'signed_in' && result.session.authMethod, 'sso');
  // The flow key is spent: the same code again is refused here too.
  assert.equal(session.size, 0);
  await assert.rejects(provider.completeSso('code-1'), (e: unknown) => e instanceof AuthError && e.code === 'invalid_token');
  await provider.signOut();
  delete (globalThis as { window?: unknown }).window;
});
