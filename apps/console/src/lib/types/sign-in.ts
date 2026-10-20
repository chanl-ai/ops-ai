/**
 * How people sign in to this workspace. The login screen offers only what the policy allows; a bank turns on SSO
 * by verified domain, requires MFA and invites people instead of letting them sign up.
 */
export type SsoProvider = 'entra' | 'okta' | 'oidc' | 'saml';

/** How one email signs in, read from its domain alone before anyone is signed in: a password, the workspace's SSO
 * provider, or both. The sign-in page shows only these. */
export interface SignInOptions {
  password: boolean;
  sso: { kind: 'oidc' | 'saml' | 'sso'; label: string } | null;
}

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

/** How a workspace's people sign in, as platform-service stores it (c-188, c-195). */
export type SignInProviderKind = 'password' | 'oidc' | 'saml';

/** The membership roles a first sign-in may give; admin is never one. */
export type JitRole = 'chat_user' | 'viewer' | 'builder' | 'approver';

/** A listed domain: it routes sign-in only once `verifiedAt` is set, after `record` was published in its DNS. */
export interface DomainCheck {
  domain: string;
  verifiedAt: string | null;
  record: { name: string; value: string };
}

export interface OidcSettings {
  issuer: string;
  clientId: string;
  /** A name from the installation's sign-in secrets; the value never reaches the console. */
  clientSecretRef: string | null;
  scopes: string[] | null;
}

export interface SamlSettings {
  idpEntityId: string;
  ssoUrl: string;
  certificate: string;
  emailAttribute: string | null;
  nameAttribute: string | null;
  /** Sign each request to the identity provider with the installation's service provider key (c-197). */
  signRequests?: boolean;
  /** Refuse an assertion the identity provider did not encrypt to the service provider certificate (c-197). */
  requireEncryption?: boolean;
}

export interface GroupRule {
  group: string;
  team: string;
  role: JitRole;
}

export interface SignInProvider {
  id: string;
  kind: SignInProviderKind;
  label: string;
  enabled: boolean;
  domains: string[];
  oidc: OidcSettings | null;
  saml: SamlSettings | null;
  /** Where a person new to the workspace lands on their first sign-in; no team means the workspace's default team. */
  jit: { team: string | null; role: JitRole } | null;
  /** Identity provider groups to teams (c-202); set through the API, kept as is by the console's form. */
  groups: { source: string | null; map: GroupRule[] } | null;
  verification: DomainCheck[];
}

export interface SignInProviderInput {
  kind: SignInProviderKind;
  label: string;
  enabled: boolean;
  domains: string[];
  oidc?: OidcSettings;
  saml?: SamlSettings;
  jit?: { team: string | null; role: JitRole };
  groups?: { source: string | null; map: GroupRule[] };
}
