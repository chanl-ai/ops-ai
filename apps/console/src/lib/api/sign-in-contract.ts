import type { SignInPolicy, SignInPolicyPatch, SsoTestResult } from '@/lib/types/sign-in';

/**
 * The workspace sign-in policy. The login screen reads `get()` (useSignInPolicy in hooks/auth-queries.ts) to decide
 * what it offers; Settings → Sign-in edits it one section at a time. Every save is audited.
 */
export interface SignInPolicyApi {
  get(): Promise<SignInPolicy>;
  /** 400 when the result would leave no way to sign in, or SSO on with no verified domain. */
  save(patch: SignInPolicyPatch): Promise<SignInPolicy>;
  /** Adds an unverified domain with the DNS TXT record to publish. 409 when already listed. */
  addDomain(domain: string): Promise<SignInPolicy>;
  /** Checks the TXT record; 422 with what was found when it does not match. */
  verifyDomain(domain: string): Promise<SignInPolicy>;
  removeDomain(domain: string): Promise<SignInPolicy>;
  /** Fetches the IdP metadata and runs a test sign-in; the result is kept on the policy. */
  testConnection(): Promise<SsoTestResult>;
}
