/** The signed-in person's own account: profile, password, MFA devices and sessions. Step-up is the AuthProvider's (lib/auth). */

export type AuthMethod = 'password' | 'sso';

export interface AccountProfile {
  id: string;
  name: string;
  email: string;
  initials: string;
  team: string;
  role: string;
  authMethod: AuthMethod;
  /** Set for SSO accounts: the identity provider that signs them in. */
  ssoProvider?: string;
}

export interface MfaDevice {
  id: string;
  kind: 'totp' | 'recovery_codes';
  label: string;
  addedAt: string;
  lastUsedAt?: string;
  /** Recovery codes only: how many are still unused. */
  remaining?: number;
}

export interface AccountSession {
  id: string;
  device: string;
  browser: string;
  location: string;
  ip: string;
  lastSeenAt: string;
  createdAt: string;
  current: boolean;
}

export type SessionFilters = { current?: string[] };
