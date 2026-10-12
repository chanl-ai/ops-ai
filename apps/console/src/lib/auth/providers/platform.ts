import type { MemberRole } from '@/lib/types/settings';

import type { SignedInIdentity } from '@/lib/api/request-identity';

import { AuthError, type AuthProvider, type Session, type SignInResult, type WorkspaceRole } from '../provider';

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

const workspaceRole = (r: MemberRole | undefined): WorkspaceRole => (r === 'admin' ? 'admin' : r === 'viewer' ? 'viewer' : 'member');

function toSession(s: Stored): Session {
  const p = s.principal;
  const role = p.roles[p.teamId ?? p.teamIds[0] ?? ''];
  return {
    user: { id: p.sub, name: p.name, email: p.email, teamIds: p.teamIds, role: workspaceRole(role), teamRoles: p.roles },
    mfaEnrolled: false,
    authMethod: 'password',
    issuedAt: s.issuedAt,
    expiresAt: s.expiresAt,
  };
}

/**
 * Email and password sign-in against platform-service, the only token issuer (docs/specs/platform-service.md). Keeps
 * the 15-minute access token and the refresh token in session storage, refreshes ahead of expiry, and hands the access
 * token and its teams to the API transport through `identity()`, and `renew()` refreshes after a service's 401. A refresh token works once: each refresh stores the new one, and
 * an in-flight refresh is shared so two callers never spend the same token (platform-service ends the session if so).
 */
export function createPlatformProvider(baseUrl: string): AuthProvider & { identity(): SignedInIdentity | null; renew(): Promise<SignedInIdentity | null> } {
  let stored: Stored | null | undefined;
  let refreshing: Promise<Stored | null> | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let checked = false;
  const listeners = new Set<(s: Session | null) => void>();

  const read = (): Stored | null => {
    if (stored !== undefined) return stored;
    try {
      const raw = typeof window === 'undefined' ? null : sessionStorage.getItem(STORAGE_KEY);
      stored = raw ? (JSON.parse(raw) as Stored) : null;
    } catch {
      stored = null;
    }
    if (stored) schedule(stored);
    return stored;
  };
  const write = (next: Stored | null) => {
    stored = next;
    try {
      if (next) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // Storage blocked (private window): the session lives in memory for this page only.
    }
    clearTimeout(timer);
    if (next) schedule(next);
    const session = next ? toSession(next) : null;
    listeners.forEach((l) => l(session));
  };
  function schedule(session: Stored) {
    if (typeof window === 'undefined') return;
    const wait = Math.max(0, new Date(session.expiresAt).getTime() - Date.now() - REFRESH_LEAD_MS);
    timer = setTimeout(() => void refresh(), wait);
  }

  async function call<T>(path: string, init: RequestInit & { token?: string } = {}): Promise<T | null> {
    const { token, ...rest } = init;
    const res = await fetch(`${baseUrl}${path}`, {
      ...rest,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (res.status === 204) return null;
    const body = await res.json().catch(() => null);
    if (res.status === 401) throw new AuthError(body?.error?.message ?? 'Sign-in failed. Check the email and password.', 'invalid_credentials');
    if (!res.ok) throw new AuthError(body?.error?.message ?? `Sign-in service answered ${res.status}.`, 'policy');
    return (body?.data ?? null) as T | null;
  }

  const keep = (issued: Issued, issuedAt = new Date().toISOString()): Stored => {
    const s = { ...issued, issuedAt };
    write(s);
    return s;
  };

  function refresh(): Promise<Stored | null> {
    const current = read();
    if (!current) return Promise.resolve(null);
    refreshing ??= call<Issued>('/v1/auth/refresh', { method: 'POST', body: JSON.stringify({ refreshToken: current.refreshToken }) })
      .then((issued) => (issued ? keep(issued, current.issuedAt) : null))
      .catch(() => {
        write(null);
        return null;
      })
      .finally(() => {
        refreshing = null;
      });
    return refreshing;
  }

  const unsupported = async (): Promise<never> => {
    throw new AuthError('Platform sign-in supports email and password only so far.', 'not_configured');
  };

  return {
    name: 'platform',
    // MFA enrolment moves to platform-service in its MFA slice (docs/specs/platform-service.md); until then it has none.
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
        } catch {
          write(null);
          return null;
        }
      }
      return current ? toSession(current) : null;
    },
    onSessionChange(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async signInWithPassword(email, password): Promise<SignInResult> {
      const issued = await call<Issued>('/v1/auth/sign-in', { method: 'POST', body: JSON.stringify({ email: email.trim(), password }) });
      if (!issued) throw new AuthError('The sign-in service returned no session.', 'policy');
      checked = true;
      return { status: 'signed_in', session: toSession(keep(issued)) };
    },
    signInWithGoogle: unsupported,
    startSso: unsupported,
    completeSso: unsupported,
    sendReset: unsupported,
    resetPassword: unsupported,
    mfa: { setup: unsupported, enrol: unsupported, verify: unsupported },
    reauthenticate: unsupported,
    startSsoStepUp: unsupported,
    completeSsoStepUp: unsupported,
    takeStepUp: () => null,
    async signOut() {
      const s = read();
      if (s) await call('/v1/auth/sign-out', { method: 'POST', token: s.token }).catch(() => undefined);
      write(null);
    },
  };
}
