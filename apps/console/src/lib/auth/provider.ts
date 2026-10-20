/**
 * The one interface the console signs people in through. Adapters (mock, platform, OIDC, Firebase) implement it; nothing
 * else imports an identity SDK. What a workspace allows (methods, SSO domains, MFA, session length) is policy from
 * the API (`api.signInPolicy`), never decided by an adapter. Workflow identity is ADR-0005 and not covered here.
 */

import type { MemberRole } from '@/lib/types/settings';
import type { SignInOptions } from '@/lib/types/sign-in';

export type { SignInOptions };

export type AuthMethod = 'password' | 'sso' | 'google';
export type WorkspaceRole = 'admin' | 'member' | 'viewer';

export interface SessionUser {
  id: string;
  name: string;
  email: string;
  teamIds: string[];
  role: WorkspaceRole;
  /** The person's role on each team (platform sign-in only). Builder and approver differ: one may not decide what the other requested. */
  teamRoles?: Record<string, MemberRole>;
}

export interface Session {
  user: SessionUser;
  mfaEnrolled: boolean;
  authMethod: AuthMethod;
  issuedAt: string;
  expiresAt: string;
}

/** A sign-in either finishes, or stops at an MFA challenge the person answers on /mfa/verify. */
export type SignInResult = { status: 'signed_in'; session: Session } | { status: 'mfa_required'; challengeId: string; email: string };

export interface MfaSetup {
  /** Base32 secret for authenticator apps that cannot scan. */
  secret: string;
  /** otpauth:// URI the QR code encodes. */
  otpauthUrl: string;
  /** Shown once; each works one time when the authenticator is lost. */
  recoveryCodes: string[];
}

/** Proof of a fresh sign-in for a sensitive action, valid for a few minutes. */
export interface StepUp {
  token: string;
  expiresAt: string;
}

/** Password accounts only. `code` is the authenticator code, required when the person has enrolled one. */
export type ReauthInput = { method: 'password'; password: string; code?: string };

export interface AuthProvider {
  readonly name: 'mock' | 'oidc' | 'firebase' | 'platform';
  /** Whether a person can enrol two-step verification through this adapter; when false the console never sends them to /mfa/setup. */
  readonly enrolsMfa: boolean;
  /** Null when nobody is signed in. An expired session is returned as is, so the console can offer to sign in again. */
  getSession(): Promise<Session | null>;
  /** Called with the new session (or null) after every sign-in, sign-out and expiry. Returns an unsubscribe. */
  onSessionChange(listener: (session: Session | null) => void): () => void;
  signInWithPassword(email: string, password: string): Promise<SignInResult>;
  signInWithGoogle(): Promise<SignInResult>;
  /** What the typed email's workspace allows, so the sign-in page shows only those methods. Needs no session. */
  signInOptions(email: string): Promise<SignInOptions>;
  /** Where to send the browser to sign in with the workspace IdP for this email or domain; the IdP's answer comes
   * back to /sso/callback with `next` carried through. */
  startSso(input: { email?: string; domain?: string; next?: string }): Promise<{ redirectUrl: string }>;
  /** Finishes SSO with the code the IdP sent back to /sso/callback. */
  completeSso(code: string): Promise<SignInResult>;
  /** Sends a reset email. `previewUrl` is set only by the mock, which has no mailbox, so the demo can follow the link. */
  sendReset(email: string): Promise<{ previewUrl?: string }>;
  resetPassword(token: string, password: string): Promise<void>;
  mfa: {
    /** Starts enrolment for the signed-in person: a new secret and recovery codes. */
    setup(): Promise<MfaSetup>;
    /** Confirms enrolment with the first code from the authenticator. */
    enrol(code: string): Promise<Session>;
    /** Answers the challenge a password sign-in stopped at. */
    verify(code: string, challengeId?: string): Promise<Session>;
  };
  /** Step-up for a password session: password, plus the authenticator code when enrolled. */
  reauthenticate(input: ReauthInput): Promise<StepUp>;
  /**
   * Step-up for an SSO or Google session: where to send the browser so the IdP confirms the person again. The IdP
   * sends it back to /sso/callback?stepUp=1, which calls completeSsoStepUp and returns to `returnTo`.
   */
  startSsoStepUp(input: { returnTo: string }): Promise<{ redirectUrl: string }>;
  /** Finishes an IdP step-up from the callback and keeps the token for takeStepUp. */
  completeSsoStepUp(code: string): Promise<StepUp>;
  /** The step-up an IdP round trip left, cleared on read so a reload does not reuse it unseen; null when none or expired. */
  takeStepUp(): StepUp | null;
  signOut(): Promise<void>;
  /** Accepts an invitation and keeps the session it starts; only adapters whose service signs the person in at accept.
   * `password` is set by a new person in a workspace that signs in by password. */
  acceptInvite?(token: string, name: string, password?: string): Promise<Session>;
}

export type AuthErrorCode = 'invalid_credentials' | 'invalid_code' | 'invalid_token' | 'not_configured' | 'no_session' | 'no_challenge' | 'code_required' | 'wrong_method' | 'policy';

// A plain field rather than a constructor parameter property: node's type stripping refuses those, and the adapter's
// node --test file imports this module.
export class AuthError extends Error {
  readonly code: AuthErrorCode;
  constructor(message: string, code: AuthErrorCode) {
    super(message);
    this.name = 'AuthError';
    this.code = code;
  }
}

export const isExpired = (s: Session) => new Date(s.expiresAt).getTime() <= Date.now();
