import type { OpsAI } from '@chanl-ai/ops-ai';

import type { Narrow } from './served';

type Platform = OpsAI['raw']['platform'];
type Reply<K extends keyof Platform> = Awaited<ReturnType<Platform[K]>>;
type Body<K extends keyof Platform> = NonNullable<NonNullable<Parameters<Platform[K]>[0]>['body']>;

/**
 * How people sign in to this workspace. The login screen offers only what the policy allows; a bank turns on SSO
 * by verified domain, requires MFA and invites people instead of letting them sign up.
 */
export type SsoProvider = 'entra' | 'okta' | 'oidc' | 'saml';

/** How one email signs in, read from its domain alone before anyone is signed in: a password, the workspace's SSO
 * provider, or both. The sign-in page shows only these. */
export type SignInOptions = Reply<'auth_sign_in_options'>;

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

/** How a workspace's people sign in, as platform-service stores it. */
export type SignInProviderKind = 'password' | 'oidc' | 'saml';

/** The membership roles a first sign-in may give; admin is never one. */
export type JitRole = 'chat_user' | 'viewer' | 'builder' | 'approver';

/** A listed domain: it routes sign-in only once `verifiedAt` is set, after `record` was published in its DNS. */
export type DomainCheck = Reply<'sign_in_providers_list_signin_providers'>[number]['verification'][number];

export type OidcSettings = NonNullable<Reply<'sign_in_providers_list_signin_providers'>[number]['oidc']>;

export type SamlSettings = NonNullable<Reply<'sign_in_providers_list_signin_providers'>[number]['saml']>;

export type GroupRule = Narrow<NonNullable<Reply<'sign_in_providers_list_signin_providers'>[number]['groups']>['map'][number], { role: JitRole }>;

export type SignInProvider = Narrow<
  Reply<'sign_in_providers_list_signin_providers'>[number],
  {
    jit: { team: string | null; role: JitRole } | null;
    /** Identity provider groups to teams; set through the API, kept as is by the console's form. */
    groups: (Omit<NonNullable<Reply<'sign_in_providers_list_signin_providers'>[number]['groups']>, 'map'> & { map: GroupRule[] }) | null;
  }
>;

type ProviderIn = Body<'sign_in_providers_save_signin_provider'>;
type SamlIn = NonNullable<ProviderIn['saml']>;

/** The schema lists the SAML switches as required although platform-service defaults them, so the console may leave them out. */
export type SignInProviderInput = Narrow<
  ProviderIn,
  {
    domains: string[];
    saml?: (Omit<SamlIn, 'requireEncryption' | 'signRequests' | 'tiles'> & Partial<Pick<SamlIn, 'requireEncryption' | 'signRequests' | 'tiles'>>) | null;
    jit?: { team: string | null; role: JitRole } | null;
    groups?: (Omit<NonNullable<ProviderIn['groups']>, 'map'> & { map: GroupRule[] }) | null;
  }
>;
