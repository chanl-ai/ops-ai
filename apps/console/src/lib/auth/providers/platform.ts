import type { MemberRole } from '@/lib/types/settings';

import type { SignedInIdentity } from '@/lib/api/request-identity';

import { AuthError, type AuthMethod, type AuthProvider, type DemoPerson, type ReauthInput, type Session, type SignInOptions, type SignInResult, type StepUp, type WorkspaceRole } from '../provider.ts';

/** platform-service's caller, as GET /v1/auth/session and the sign-in response return it. */
interface Principal {
  kind: 'person' | 'api_key' | 'service';
  sub: string;
  email: string;
  name: string;
  tenantId: string;
  /** Null for a person on several teams. */
  teamId: string | null;
  teamIds: string[];
  roles: Record<string, MemberRole>;
  scopes: string[];
  authMethod: string;
}

interface Issued {
  token: string;
  refreshToken: string;
  expiresAt: string;
  principal: Principal;
}

interface Stored extends Issued {
  issuedAt: string;
}

const STORAGE_KEY = 'ops-platform-session';
/** Refresh this long before the access token expires, so a call never carries one that lapses in flight. */
const REFRESH_LEAD_MS = 60_000;
/** After a refresh that failed for a reason other than a refusal (network, a restarting service), try again this soon. */
const RETRY_MS = 15_000;
/** Held while one tab refreshes, so tabs sharing the session never spend the same refresh token twice. */
const REFRESH_LOCK = 'ops-platform-refresh';
/** The flow key of this tab's SSO round trip: platform-service completes the round trip only alongside it, so a code
 * that leaks out of the address bar opens nothing in another browser. Tab storage, because the round trip is this tab's. */
const FLOW_KEY = 'ops-platform-sso-flow';
/** A step-up an IdP round trip left, for the page that asked for it (`takeStepUp`). */
const STEP_UP_KEY = 'ops-platform-step-up';

/** Only a 401 means the session is over; anything else (offline, a 5xx while a service restarts) is worth retrying. */
const refused = (e: unknown) => e instanceof AuthError && e.code === 'invalid_credentials';

/**
 * Local storage, so every tab shares one session: per-tab storage signed out each new tab, and a duplicated tab carried a
 * copy of the refresh token that the other tab then spent, which platform-service treats as reuse and ends the session.
 */
function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** Tab storage for the SSO round trip; null where storage is blocked. */
function tabStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

const workspaceRole = (r: MemberRole | undefined): WorkspaceRole => (r === 'admin' ? 'admin' : r === 'viewer' ? 'viewer' : 'member');

/** platform-service's `authMethod` as the console names it: OIDC and SAML sessions step up at their IdP. */
const methodOf = (m: string): AuthMethod => (m === 'oidc' || m === 'saml' ? 'sso' : 'password');

function toSession(s: Stored): Session {
  const p = s.principal;
  const role = p.roles[p.teamId ?? p.teamIds[0] ?? ''];
  return {
    user: { id: p.sub, name: p.name, email: p.email, teamIds: p.teamIds, role: workspaceRole(role), teamRoles: p.roles },
    mfaEnrolled: false,
    authMethod: methodOf(p.authMethod),
    issuedAt: s.issuedAt,
    expiresAt: s.expiresAt,
  };
}

/**
 * Email and password sign-in against platform-service, the only token issuer (.codeloop/wiki/concepts/platform-service.md). Keeps
 * the 15-minute access token and the refresh token in local storage, shared by every tab, refreshes ahead of expiry, and
 * hands the access token and its teams to the API transport through `identity()`; `renew()` refreshes after a service's
 * 401. A refresh token works once (platform-service ends the session if one is spent twice), so a refresh runs under a
 * cross-tab lock and first re-reads storage: when another tab already refreshed, this tab takes its tokens instead.
 * Only a 401 signs out; a network error or a 5xx keeps the session and retries.
 */
export function createPlatformProvider(baseUrl: string): AuthProvider & { identity(): SignedInIdentity | null; renew(): Promise<SignedInIdentity | null> } {
  let stored: Stored | null | undefined;
  let refreshing: Promise<Stored | null> | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let checked = false;
  const listeners = new Set<(s: Session | null) => void>();

  const load = (): Stored | null => {
    try {
      const shared = storage();
      // A tab signed in before the session moved to local storage keeps it, once, instead of signing in again.
      const legacy = shared && !shared.getItem(STORAGE_KEY) ? window.sessionStorage?.getItem(STORAGE_KEY) : null;
      if (legacy) {
        shared?.setItem(STORAGE_KEY, legacy);
        window.sessionStorage.removeItem(STORAGE_KEY);
      }
      const raw = shared?.getItem(STORAGE_KEY) ?? null;
      return raw ? (JSON.parse(raw) as Stored) : null;
    } catch {
      return null;
    }
  };
  const read = (): Stored | null => {
    if (stored !== undefined) return stored;
    stored = load();
    if (stored) schedule(stored);
    return stored;
  };
  const adopt = (next: Stored | null) => {
    stored = next;
    clearTimeout(timer);
    if (next) schedule(next);
    const session = next ? toSession(next) : null;
    listeners.forEach((l) => l(session));
  };
  const write = (next: Stored | null) => {
    try {
      if (next) storage()?.setItem(STORAGE_KEY, JSON.stringify(next));
      else storage()?.removeItem(STORAGE_KEY);
    } catch {
      // Storage blocked (private window): the session lives in memory for this page only.
    }
    adopt(next);
  };
  function schedule(session: Stored, wait = new Date(session.expiresAt).getTime() - Date.now() - REFRESH_LEAD_MS) {
    if (typeof window === 'undefined') return;
    timer = setTimeout(() => void refresh(), Math.max(0, wait));
  }
  // Another tab signed in, refreshed or signed out: follow it, so no tab keeps a refresh token that was already spent.
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => {
      if (e.key === STORAGE_KEY && stored !== undefined) adopt(load());
    });
  }

  async function call<T>(path: string, init: RequestInit & { token?: string } = {}): Promise<T | null> {
    const { token, ...rest } = init;
    const res = await fetch(`${baseUrl}${path}`, {
      ...rest,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (res.status === 204) return null;
    const body = await res.json().catch(() => null);
    if (res.status === 401) throw new AuthError(body?.error?.message ?? 'Sign-in failed. Check the email and password.', 'invalid_credentials', 401);
    if (!res.ok) throw new AuthError(body?.error?.message ?? `Sign-in service answered ${res.status}.`, 'policy', res.status);
    return (body?.data ?? null) as T | null;
  }

  const keep = (issued: Issued, issuedAt = new Date().toISOString()): Stored => {
    const s = { ...issued, issuedAt };
    write(s);
    return s;
  };

  async function rotate(seen: Stored): Promise<Stored | null> {
    // Inside the lock: if another tab rotated while this one waited, its tokens are in storage; use them.
    const latest = load();
    if (!latest) return null;
    if (latest.refreshToken !== seen.refreshToken && new Date(latest.expiresAt).getTime() - Date.now() > REFRESH_LEAD_MS) {
      adopt(latest);
      return latest;
    }
    try {
      const issued = await call<Issued>('/v1/auth/refresh', { method: 'POST', body: JSON.stringify({ refreshToken: latest.refreshToken }) });
      return issued ? keep(issued, latest.issuedAt) : null;
    } catch (e) {
      if (refused(e)) {
        write(null);
        return null;
      }
      // Offline or a service restarting: keep the session and try again shortly.
      clearTimeout(timer);
      schedule(latest, RETRY_MS);
      return latest;
    }
  }

  function refresh(): Promise<Stored | null> {
    const current = read();
    if (!current) return Promise.resolve(null);
    const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
    if (!refreshing) {
      // The lib types the lock's result as a promise of the callback's promise; `then` flattens it as the runtime does.
      const run = locks ? locks.request(REFRESH_LOCK, () => rotate(current)).then((r) => r) : rotate(current);
      refreshing = run.finally(() => {
        refreshing = null;
      });
    }
    return refreshing;
  }

  const unsupported = async (): Promise<never> => {
    throw new AuthError('Platform sign-in has no Google or authenticator-app sign-in yet.', 'not_configured');
  };

  /** Starts an IdP round trip and keeps its flow key in this tab. */
  async function begin(path: string, body: Record<string, unknown>, token?: string): Promise<{ redirectUrl: string }> {
    const started = await call<{ redirectUrl: string; flowKey: string }>(path, { method: 'POST', token, body: JSON.stringify(body) });
    if (!started) throw new AuthError('The sign-in service returned no sign-in address.', 'policy');
    tabStorage()?.setItem(FLOW_KEY, started.flowKey);
    return { redirectUrl: started.redirectUrl };
  }
  /** This tab's flow key, cleared on read: a round trip completes once. */
  const flowKey = (): string => {
    const key = tabStorage()?.getItem(FLOW_KEY);
    tabStorage()?.removeItem(FLOW_KEY);
    if (!key) throw new AuthError('This sign-in was started in another tab or browser. Start again here.', 'invalid_token');
    return key;
  };

  return {
    name: 'platform',
    // MFA enrolment moves to platform-service in its MFA slice (.codeloop/wiki/concepts/platform-service.md); until then it has none.
    enrolsMfa: false,
    identity: () => {
      const s = read();
      return s ? { token: s.token, teamIds: s.principal.teamIds } : null;
    },
    renew: async () => {
      const s = await refresh();
      return s ? { token: s.token, teamIds: s.principal.teamIds } : null;
    },
    async getSession() {
      let current = read();
      if (!current) return null;
      if (new Date(current.expiresAt).getTime() - Date.now() < REFRESH_LEAD_MS) current = await refresh();
      // Once per page load, confirm the session was not ended elsewhere (sign-out answers 401 before the token expires).
      if (current && !checked) {
        checked = true;
        try {
          await call<Principal>('/v1/auth/session', { token: current.token });
        } catch (e) {
          // Signed out elsewhere answers 401; a service that is down for a moment does not end the session.
          if (refused(e)) {
            write(null);
            return null;
          }
          checked = false;
        }
      }
      return current ? toSession(current) : null;
    },
    onSessionChange(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async signInWithPassword(email, password): Promise<SignInResult> {
      // platform-service answers every 401 with "Sign in again."; on this form a 401 means the email and password.
      const issued = await call<Issued>('/v1/auth/sign-in', { method: 'POST', body: JSON.stringify({ email: email.trim(), password }) }).catch((e: unknown) => {
        throw e instanceof AuthError && e.status === 401 ? new AuthError('Sign-in failed. Check the email and password.', 'invalid_credentials', 401) : e;
      });
      if (!issued) throw new AuthError('The sign-in service returned no session.', 'policy');
      checked = true;
      return { status: 'signed_in', session: toSession(keep(issued)) };
    },
    async demoPeople(): Promise<DemoPerson[]> {
      // The routes exist only on a development platform-service; anywhere else the 404 means there are none.
      return (await call<DemoPerson[]>('/v1/auth/dev-people').catch((e: unknown) => {
        if (e instanceof AuthError && e.status === 404) return [];
        throw e;
      })) ?? [];
    },
    async signInAsDemo(email): Promise<SignInResult> {
      const issued = await call<Issued>('/v1/auth/dev-sign-in', { method: 'POST', body: JSON.stringify({ email }) });
      if (!issued) throw new AuthError('The sign-in service returned no session.', 'policy');
      checked = true;
      return { status: 'signed_in', session: toSession(keep(issued)) };
    },
    signInWithGoogle: unsupported,
    async signInOptions(email): Promise<SignInOptions> {
      const options = await call<SignInOptions>('/v1/auth/options', { method: 'POST', body: JSON.stringify({ email: email.trim() }) });
      return options ?? { password: true, sso: null };
    },
    startSso: async ({ email, next }) => {
      if (!email) throw new AuthError('Enter your work email.', 'invalid_credentials');
      return begin('/v1/auth/sso/start', { email: email.trim(), ...(next ? { next } : {}) });
    },
    async completeSso(code): Promise<SignInResult> {
      const issued = await call<Issued>('/v1/auth/sso/complete', { method: 'POST', body: JSON.stringify({ code, flowKey: flowKey() }) });
      if (!issued) throw new AuthError('The sign-in service returned no session.', 'policy');
      checked = true;
      return { status: 'signed_in', session: toSession(keep(issued)) };
    },
    /** platform-service mails the link itself; it never hands it back, so there is no preview here. */
    async sendReset(email) {
      await call('/v1/auth/password/forgot', { method: 'POST', body: JSON.stringify({ email: email.trim() }) });
      return {};
    },
    async resetPassword(token, password) {
      await call('/v1/auth/password/reset', { method: 'POST', body: JSON.stringify({ token, password }) });
    },
    mfa: { setup: unsupported, enrol: unsupported, verify: unsupported },
    /** The password again, to platform-service, which signs a five-minute step-up the agents service accepts. No MFA yet, so `code` is unused. */
    async reauthenticate(input: ReauthInput): Promise<StepUp> {
      const s = read();
      if (!s) throw new AuthError('Sign in before confirming your identity.', 'no_session');
      const issued = await call<StepUp>('/v1/auth/step-up', { method: 'POST', token: s.token, body: JSON.stringify({ password: input.password }) });
      if (!issued) throw new AuthError('The sign-in service returned no step-up.', 'policy');
      return issued;
    },
    /** An SSO session's step-up: back to its own IdP, which asks for credentials again, then to /sso/callback?stepUp=1. */
    async startSsoStepUp({ returnTo }) {
      const s = read();
      if (!s) throw new AuthError('Sign in before confirming your identity.', 'no_session');
      return begin('/v1/auth/step-up/sso/start', { next: returnTo }, s.token);
    },
    async completeSsoStepUp(code): Promise<StepUp> {
      const s = read();
      if (!s) throw new AuthError('Sign in before confirming your identity.', 'no_session');
      const up = await call<StepUp>('/v1/auth/step-up/sso/complete', { method: 'POST', token: s.token, body: JSON.stringify({ code, flowKey: flowKey() }) });
      if (!up) throw new AuthError('The sign-in service returned no step-up.', 'policy');
      tabStorage()?.setItem(STEP_UP_KEY, JSON.stringify(up));
      return up;
    },
    takeStepUp() {
      const raw = tabStorage()?.getItem(STEP_UP_KEY);
      tabStorage()?.removeItem(STEP_UP_KEY);
      if (!raw) return null;
      try {
        const up = JSON.parse(raw) as StepUp;
        return new Date(up.expiresAt).getTime() > Date.now() ? up : null;
      } catch {
        return null;
      }
    },
    /** platform-service answers an accepted invitation with a session that already carries the team. The signed-in
     * person's token goes with it: an invitation to an existing account is accepted only by that person. */
    async acceptInvite(token, name, password) {
      const current = read();
      const body = { name, ...(password && !current ? { password } : {}) };
      const issued = await call<Issued>(`/v1/invites/${encodeURIComponent(token)}/accept`, { method: 'POST', token: current?.token, body: JSON.stringify(body) });
      if (!issued) throw new AuthError('The sign-in service returned no session.', 'policy');
      checked = true;
      return toSession(keep(issued));
    },
    async signOut() {
      const s = read();
      if (s) await call('/v1/auth/sign-out', { method: 'POST', token: s.token }).catch(() => undefined);
      write(null);
    },
  };
}
