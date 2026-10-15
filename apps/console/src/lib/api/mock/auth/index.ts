import { AuthError, type AuthProvider, type MfaSetup, type Session, type SignInResult, type StepUp, type WorkspaceRole } from '@/lib/auth/provider';

import { auditSink } from '../governance';
import { currentSignInPolicy } from '../sign-in-policy';
import { ABSOLUTE_SESSION_HOURS, DEFAULT_USER_ID, DEMO_TOTP, type MockUser, USERS } from './seed';

const KEY = 'ops-auth';

/** People added at runtime by other mocks (an accepted invite), signed in like the seeded ones. */
const registered: MockUser[] = [];

/**
 * Adds someone the adapter can sign in, for the invites mock on accept. They start without MFA, so a policy that
 * requires it sends them to /mfa/setup after their first sign-in.
 */
export function registerMockUser(u: { email: string; name: string; teamIds: string[]; role: WorkspaceRole; method: 'password' | 'sso'; password: string | null }): void {
  const email = u.email.trim().toLowerCase();
  const existing = registered.findIndex((x) => x.email === email);
  const user: MockUser = { id: `usr_reg_${btoa(email).replace(/[^a-z0-9]/gi, '').slice(0, 8)}`, name: u.name, email, teamIds: u.teamIds, role: u.role, password: u.password, mfaEnrolled: false, method: u.method };
  if (existing >= 0) registered[existing] = user;
  else registered.push(user);
}
const HOUR = 3_600_000;

interface Stored {
  /** `signed_out` is remembered so the demo stays signed out across reloads until someone signs in. */
  state: 'signed_in' | 'signed_out';
  session?: Session;
  challenge?: { id: string; userId: string };
  /** Passwords changed through reset, by user id. */
  passwords: Record<string, string>;
  resets: Record<string, string>;
  enrolled: Record<string, boolean>;
  ssoUsers: Record<string, MockUser>;
  /** Step-up tokens reauthenticate issued, reusable until they expire so one step-up covers a batch. */
  stepUps?: Record<string, { email: string; expiresAt: string }>;
  /** The token an IdP step-up round trip left for takeStepUp. */
  pendingStepUp?: StepUp;
  /** Idle limit read from policy at sign-in, and the absolute end; later policy changes apply from the next sign-in. */
  limits?: { idleHours: number; absoluteAt: string };
}

const STEP_UP_MS = 5 * 60_000;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const METHOD_LABEL: Record<Session['authMethod'], string> = { password: 'password', sso: 'single sign-on', google: 'Google' };
const IDP_LABEL = { entra: 'Microsoft Entra ID', okta: 'Okta', oidc: 'your identity provider', saml: 'your identity provider' } as const;

/** Sign-in events go to Activity → Audit log as the person they concern, which may not be who the console runs as. */
function auditSession(action: 'login' | 'rejected' | 'edited' | 'revoked' | 'approved', who: { email: string; name?: string }, summary: string) {
  const email = who.email.trim().toLowerCase();
  auditSink.log({ action, target: { type: 'session', name: email, href: '/account/security' }, summary, actor: { kind: 'person', name: who.name ?? email, detail: email } });
}

/** Set by the adapter instance so other mocks (account security) read and change the same state. */
let bridge: { user: () => MockUser | null; setPassword: (email: string, password: string) => void; stepUp: (token: string) => { email: string; expiresAt: string } | undefined } | null = null;

/** The person behind the current mock session, for mocks that act as them; null when signed out. */
export function currentMockUser(): { id: string; email: string; name: string; method: MockUser['method']; mfaEnrolled: boolean } | null {
  const u = bridge?.user();
  return u ? { id: u.id, email: u.email, name: u.name, method: u.method, mfaEnrolled: u.mfaEnrolled } : null;
}

/** Checks a step-up token from reauthenticate, for mocks that guard step-up approvals. */
export function verifyMockStepUp(token: string): { ok: true; email: string } | { ok: false; reason: 'unknown' | 'expired' } {
  const t = token ? bridge?.stepUp(token) : undefined;
  if (!t) return { ok: false, reason: 'unknown' };
  if (new Date(t.expiresAt).getTime() <= Date.now()) return { ok: false, reason: 'expired' };
  return { ok: true, email: t.email };
}

/** Records a new password the way a reset does, so a password change is what sign-in accepts next. */
export function setMockPassword(email: string, password: string): void {
  bridge?.setPassword(email, password);
}

/**
 * Instant, in-browser sign-in for demos and UI review. State lives in sessionStorage for the tab (memory when it is
 * blocked). ?mock=signed-out and ?mock=expired switch to the two designed states, as ?mock= does for the API.
 */
/**
 * `stepUpUrl`: the agents service that verifies step-up decisions. When set, "Confirm it is you" also re-authenticates
 * there and keeps the signed step-up token it returns, because that service refuses a token it did not mint.
 */
export function createMockAuthProvider(opts: { stepUpUrl?: string } = {}): AuthProvider {
  let memory: Stored | null = null;
  const listeners = new Set<(s: Session | null) => void>();

  const read = (): Stored => {
    if (memory) return memory;
    try {
      const raw = typeof window !== 'undefined' ? sessionStorage.getItem(KEY) : null;
      if (raw) return (memory = JSON.parse(raw) as Stored);
    } catch {
      // Blocked or corrupt storage: start from the default below.
    }
    const limits = limitsNow();
    return (memory = { state: 'signed_in', session: sessionFor(userById(DEFAULT_USER_ID)!, 'password', limits), limits, passwords: {}, resets: {}, enrolled: {}, ssoUsers: {} });
  };
  const write = (s: Stored) => {
    memory = s;
    try {
      sessionStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      // Memory keeps it for this page.
    }
  };
  const emit = () => {
    const s = current();
    listeners.forEach((l) => l(s));
  };

  const userById = (uid: string): MockUser | undefined => [...USERS, ...registered].find((u) => u.id === uid) ?? Object.values(memory?.ssoUsers ?? {}).find((u) => u.id === uid);
  const userByEmail = (email: string) => [...USERS, ...registered].find((u) => u.email === email.trim().toLowerCase());
  /** Session length is read from policy now; `sessionHours` is the idle limit, capped by the absolute end. */
  const limitsNow = (): NonNullable<Stored['limits']> => ({ idleHours: currentSignInPolicy().sessionHours, absoluteAt: new Date(Date.now() + ABSOLUTE_SESSION_HOURS * HOUR).toISOString() });
  const expiryFrom = (limits: NonNullable<Stored['limits']>, from = Date.now()) => new Date(Math.min(from + limits.idleHours * HOUR, new Date(limits.absoluteAt).getTime())).toISOString();
  function sessionFor(u: MockUser, method: Session['authMethod'], limits = limitsNow()): Session {
    const now = Date.now();
    // SSO and Google people have no console authenticator: their IdP applies MFA, and step-up goes back to it.
    const mfaEnrolled = method === 'password' ? (memory?.enrolled[u.id] ?? u.mfaEnrolled) : false;
    return { user: { id: u.id, name: u.name, email: u.email, teamIds: u.teamIds, role: u.role }, mfaEnrolled, authMethod: method, issuedAt: new Date(now).toISOString(), expiresAt: expiryFrom(limits, now) };
  }

  /** Applies ?mock=signed-out or ?mock=expired once per page load. */
  let urlApplied = false;
  const applyUrl = () => {
    if (urlApplied || typeof window === 'undefined') return;
    urlApplied = true;
    const q = new URLSearchParams(window.location.search).get('mock');
    const s = read();
    if (q === 'signed-out') write({ ...s, state: 'signed_out', session: undefined });
    if (q === 'expired' && s.session) write({ ...s, session: { ...s.session, issuedAt: new Date(Date.now() - (ABSOLUTE_SESSION_HOURS + 1) * HOUR).toISOString(), expiresAt: new Date(Date.now() - HOUR).toISOString() } });
  };
  /** Activity slides the idle limit forward, never past the absolute end; an expired session stays expired. */
  const touch = (s: Stored): Stored => {
    if (!s.session || !s.limits || new Date(s.session.expiresAt).getTime() <= Date.now()) return s;
    const expiresAt = expiryFrom(s.limits);
    if (expiresAt === s.session.expiresAt) return s;
    const next = { ...s, session: { ...s.session, expiresAt } };
    write(next);
    return next;
  };
  const current = (): Session | null => {
    applyUrl();
    const s = touch(read());
    return s.state === 'signed_in' && s.session ? s.session : null;
  };
  const signIn = (u: MockUser, method: Session['authMethod']): Session => {
    const limits = limitsNow();
    const session = sessionFor(u, method, limits);
    write({ ...read(), state: 'signed_in', session, limits, challenge: undefined, pendingStepUp: undefined });
    auditSession('login', u, `Signed in with ${METHOD_LABEL[method]}`);
    emit();
    return session;
  };
  /** Refuses with an audit row, so failed attempts show in Activity → Audit log like successful ones. */
  const refuse = (who: { email: string; name?: string }, auditSummary: string, err: AuthError): never => {
    auditSession('rejected', who, auditSummary);
    throw err;
  };
  const issueStepUp = (email: string, minted?: StepUp): StepUp => {
    const token = minted?.token ?? `stepup_${Math.random().toString(36).slice(2, 10)}`;
    const expiresAt = minted?.expiresAt ?? new Date(Date.now() + STEP_UP_MS).toISOString();
    const st = read();
    write({ ...st, stepUps: { ...st.stepUps, [token]: { email, expiresAt } } });
    return { token, expiresAt };
  };
  /** The agents service's signed step-up for the same re-authentication: a password, or the IdP's callback code. */
  const mintRemote = async (path: '/v1/auth/step-up' | '/v1/auth/step-up/sso', proof: Record<string, string>): Promise<StepUp | undefined> => {
    if (!opts.stepUpUrl) return undefined;
    const res = await fetch(`${opts.stepUpUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(proof),
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new AuthError(body?.error?.message ?? 'Step-up failed. Try again.', 'invalid_credentials');
    return body.data as StepUp;
  };
  const idpName = () => IDP_LABEL[currentSignInPolicy().sso.provider];
  /** The verified SSO domain for an email when SSO is on; such people's passwords live with the IdP. */
  const ssoDomainOf = (email: string) => {
    const p = currentSignInPolicy();
    const host = email.trim().toLowerCase().split('@')[1];
    return p.methods.sso && host ? p.sso.domains.find((d) => d.verified && d.domain === host)?.domain : undefined;
  };
  const passwordOf = (u: MockUser) => read().passwords[u.id] ?? u.password;

  bridge = {
    user: () => {
      const s = current();
      const u = s ? userById(s.user.id) : undefined;
      return u ? { ...u, mfaEnrolled: read().enrolled[u.id] ?? u.mfaEnrolled, method: s!.authMethod } : null;
    },
    setPassword: (email, password) => {
      const u = userByEmail(email) ?? Object.values(read().ssoUsers).find((x) => x.email === email.trim().toLowerCase());
      if (!u) return;
      const s = read();
      write({ ...s, passwords: { ...s.passwords, [u.id]: password } });
    },
    stepUp: (token) => read().stepUps?.[token],
  };

  const api: AuthProvider = {
    name: 'mock',
    enrolsMfa: true,
    getSession: async () => current(),
    onSessionChange: (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    signInWithPassword: async (email, password): Promise<SignInResult> => {
      const u = userByEmail(email);
      const who = u ?? { email };
      if (!currentSignInPolicy().methods.password) refuse(who, 'Sign-in refused: password sign-in is off in the sign-in policy', new AuthError('Password sign-in is turned off in this workspace’s sign-in policy. Sign in with SSO instead.', 'policy'));
      if (!u || !passwordOf(u) || passwordOf(u) !== password) refuse(who, 'Sign-in failed: wrong email or password', new AuthError('That email and password do not match. Try again or reset your password.', 'invalid_credentials'));
      if (!u) throw new AuthError('That email and password do not match. Try again or reset your password.', 'invalid_credentials');
      if (read().enrolled[u.id] ?? u.mfaEnrolled) {
        const challengeId = `mfa_${Math.random().toString(36).slice(2, 8)}`;
        write({ ...read(), challenge: { id: challengeId, userId: u.id } });
        return { status: 'mfa_required', challengeId, email: u.email };
      }
      return { status: 'signed_in', session: signIn(u, 'password') };
    },
    signInWithGoogle: async () => {
      if (!currentSignInPolicy().methods.google) throw new AuthError('Google sign-in is turned off in this workspace’s sign-in policy.', 'policy');
      throw new AuthError('Google sign-in is on in the policy but has no Google client set up yet.', 'not_configured');
    },
    startSso: async ({ email, domain }) => {
      const who = (email ?? `sso.user@${domain}`).trim().toLowerCase();
      const host = (domain ?? who.split('@')[1] ?? '').trim().toLowerCase();
      const p = currentSignInPolicy();
      if (!p.methods.sso) refuse({ email: who }, 'Sign-in refused: SSO is off in the sign-in policy', new AuthError('Single sign-on is turned off in this workspace’s sign-in policy.', 'policy'));
      if (!p.sso.domains.some((d) => d.verified && d.domain === host)) refuse({ email: who }, `Sign-in refused: ${host || 'no domain'} is not a verified SSO domain`, new AuthError(`${host || 'That domain'} is not a verified SSO domain in this workspace’s sign-in policy. Use your work email, or sign in with your password.`, 'policy'));
      // The mock IdP approves at once and sends the browser straight back with a code.
      return { redirectUrl: `/sso/callback?code=${encodeURIComponent(btoa(who))}` };
    },
    completeSso: async (code) => {
      let email: string;
      try {
        email = atob(decodeURIComponent(code));
      } catch {
        throw new AuthError('The sign-in link from your identity provider is not valid. Start again.', 'invalid_token');
      }
      if (!EMAIL_RE.test(email)) throw new AuthError('The sign-in link from your identity provider is not valid. Start again.', 'invalid_token');
      const s = read();
      const known = USERS.find((x) => x.email === email) ?? s.ssoUsers[email];
      const name = email.split('@')[0].split(/[._-]/).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
      // The IdP enforces its own MFA, so an SSO session never stops at the console's challenge and has no authenticator here.
      const u: MockUser = known ?? { id: `usr_sso_${btoa(email).replace(/[^a-z0-9]/gi, '').slice(0, 8)}`, name, email, teamIds: ['team_platform'], role: 'member', password: null, mfaEnrolled: false, method: 'sso' };
      if (!known) write({ ...s, ssoUsers: { ...s.ssoUsers, [email]: u } });
      return { status: 'signed_in', session: signIn(u, 'sso') };
    },
    sendReset: async (email) => {
      // SSO people have no console password to reset; their IdP owns it.
      if (ssoDomainOf(email)) throw new AuthError(`Your password is managed by ${idpName()}.`, 'policy');
      const u = userByEmail(email);
      // The same answer either way, so the form never reveals which emails have accounts.
      if (!u) return {};
      const token = `rst_${Math.random().toString(36).slice(2, 10)}`;
      const s = read();
      write({ ...s, resets: { ...s.resets, [token]: u.id } });
      return { previewUrl: `/reset-password/${token}` };
    },
    resetPassword: async (token, password) => {
      const s = read();
      const uid = s.resets[token];
      if (!uid) throw new AuthError('This reset link has expired or was already used. Ask for a new one.', 'invalid_token');
      if (password.length < 12) throw new AuthError('Use at least 12 characters.', 'invalid_credentials');
      const resets = { ...s.resets };
      delete resets[token];
      write({ ...s, resets, passwords: { ...s.passwords, [uid]: password } });
      const u = userById(uid);
      if (u) auditSession('edited', u, 'Reset password with an emailed link');
    },
    mfa: {
      setup: async (): Promise<MfaSetup> => {
        const s = current();
        if (!s) throw new AuthError('Sign in before setting up two-step verification.', 'no_session');
        const secret = 'JBSWY3DPEHPK3PXP';
        return { secret, otpauthUrl: `otpauth://totp/Northfield%20Ops%20AI:${encodeURIComponent(s.user.email)}?secret=${secret}&issuer=Northfield%20Ops%20AI`, recoveryCodes: ['4F7K-2M9Q', '8XWD-6HRT', 'C3PN-9VZL', 'J5QB-1EYU', 'M8TG-4KAD', 'R2HX-7WNC', 'V6LS-3PJF', 'Z9EM-5BQR'] };
      },
      enrol: async (code) => {
        const s = read();
        if (!s.session) throw new AuthError('Sign in before setting up two-step verification.', 'no_session');
        if (code.replace(/\s/g, '') !== DEMO_TOTP) throw new AuthError('That code is not right. Enter the 6 digits your app shows now.', 'invalid_code');
        const session = { ...s.session, mfaEnrolled: true };
        write({ ...s, session, enrolled: { ...s.enrolled, [s.session.user.id]: true } });
        auditSession('edited', s.session.user, 'Turned on two-step verification with an authenticator app');
        emit();
        return session;
      },
      verify: async (code, challengeId) => {
        const s = read();
        if (!s.challenge || (challengeId && challengeId !== s.challenge.id)) throw new AuthError('This sign-in has timed out. Sign in again.', 'no_challenge');
        const challenged = userById(s.challenge.userId);
        if (code.replace(/\s/g, '') !== DEMO_TOTP) refuse(challenged ?? { email: 'unknown' }, 'Sign-in failed: wrong two-step verification code', new AuthError('That code is not right. Enter the 6 digits your app shows now.', 'invalid_code'));
        const u = challenged;
        if (!u) throw new AuthError('This sign-in has timed out. Sign in again.', 'no_challenge');
        return signIn(u, 'password');
      },
    },
    reauthenticate: async (input) => {
      const s = current();
      if (!s) throw new AuthError('Sign in again to continue.', 'no_session');
      if (s.authMethod !== 'password') throw new AuthError(`Your account signs in through your company. Verify with ${s.authMethod === 'google' ? 'Google' : idpName()} instead.`, 'wrong_method');
      const u = userById(s.user.id);
      if (!u || passwordOf(u) !== input.password) refuse(s.user, 'Step-up failed: wrong password', new AuthError('That password is not right.', 'invalid_credentials'));
      if (s.mfaEnrolled) {
        if (!input.code?.trim()) throw new AuthError('Enter the code from your authenticator app too.', 'code_required');
        if (input.code.replace(/\s/g, '') !== DEMO_TOTP) refuse(s.user, 'Step-up failed: wrong authenticator code', new AuthError('That code is not right.', 'invalid_code'));
      }
      auditSession('approved', s.user, s.mfaEnrolled ? 'Step-up verified with password and authenticator code' : 'Step-up verified with password');
      return issueStepUp(s.user.email, await mintRemote('/v1/auth/step-up', input.code?.trim() ? { password: input.password, code: input.code.replace(/\s/g, '') } : { password: input.password }));
    },
    startSsoStepUp: async ({ returnTo }) => {
      const s = current();
      if (!s) throw new AuthError('Sign in again to continue.', 'no_session');
      if (s.authMethod === 'password') throw new AuthError('Your account signs in with a password. Confirm with your password instead.', 'wrong_method');
      // The mock IdP confirms at once and sends the browser back with a code naming the person.
      return { redirectUrl: `/sso/callback?stepUp=1&code=${encodeURIComponent(btoa(s.user.email))}&next=${encodeURIComponent(returnTo)}` };
    },
    completeSsoStepUp: async (code) => {
      const s = current();
      if (!s) throw new AuthError('Sign in again to continue.', 'no_session');
      let email = '';
      try {
        email = atob(decodeURIComponent(code)).trim().toLowerCase();
      } catch {
        // Falls through to the refusal below.
      }
      if (email !== s.user.email) refuse(s.user, `Step-up failed: ${idpName()} returned ${email || 'an unreadable answer'}`, new AuthError(`${idpName()} confirmed a different account. Sign in to ${idpName()} as ${s.user.email} and try again.`, 'invalid_token'));
      auditSession('approved', s.user, `Step-up verified with ${s.authMethod === 'google' ? 'Google' : idpName()}`);
      const stepUp = issueStepUp(s.user.email, await mintRemote('/v1/auth/step-up/sso', { code }));
      write({ ...read(), pendingStepUp: stepUp });
      return stepUp;
    },
    takeStepUp: () => {
      const st = read();
      const p = st.pendingStepUp;
      if (!p) return null;
      write({ ...st, pendingStepUp: undefined });
      return new Date(p.expiresAt).getTime() > Date.now() ? p : null;
    },
    signOut: async () => {
      const was = read().session;
      write({ ...read(), state: 'signed_out', session: undefined, challenge: undefined, pendingStepUp: undefined, limits: undefined });
      if (was) auditSession('revoked', was.user, 'Signed out');
      emit();
    },
  };
  return api;
}
