/**
 * How people sign in to this workspace. The login screen offers only what the policy allows; a bank turns on SSO
 * by verified domain, requires MFA and invites people instead of letting them sign up.
 */
export type SsoProvider = 'entra' | 'okta' | 'oidc' | 'saml';

export interface SsoDomain {
  domain: string;
  verified: boolean;
  /** The DNS TXT record to publish before verifying. */
  txtRecord: string;
  verifiedAt?: string;
}

export interface SsoTestResult {
  ok: boolean;
  at: string;
  message: string;
}

export interface SignInPolicy {
  methods: { password: boolean; sso: boolean; google: boolean };
  sso: { provider: SsoProvider; metadataUrl: string; metadataFileId?: string; metadataFileName?: string; domains: SsoDomain[]; lastTest?: SsoTestResult };
  mfaRequired: boolean;
  /** Hours a session stays signed in without activity. */
  sessionHours: number;
  /** Email domains people can be invited from; empty means any. */
  allowedDomains: string[];
  selfSignup: boolean;
  updatedAt: string;
  updatedBy: string;
}

/** Each section of Settings → Sign-in saves on its own. */
export type SignInPolicySection = 'methods' | 'sso' | 'security' | 'signup';

export type SignInPolicyPatch =
  | { section: 'methods'; methods: SignInPolicy['methods'] }
  | { section: 'sso'; provider: SsoProvider; metadataUrl: string; metadataFileId?: string; metadataFileName?: string }
  | { section: 'security'; mfaRequired: boolean; sessionHours: number; allowedDomains: string[] }
  | { section: 'signup'; selfSignup: boolean };
