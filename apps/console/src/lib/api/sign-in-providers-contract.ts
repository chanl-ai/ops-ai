import type { SignInProvider, SignInProviderInput } from '@/lib/types/sign-in';

/**
 * A workspace's sign-in providers on platform-service (c-195): Security team admins set an OIDC or SAML provider with
 * its domains, and prove each domain by a DNS TXT record before it routes anyone. Every write is audited there.
 */
export interface SignInProvidersApi {
  /** 403 for someone without settings.view. */
  list(): Promise<SignInProvider[]>;
  /** Creates or replaces by id. 400 with the server's reason (`secret_missing`, `certificate`, `jit_role`…), 409 `domain_taken`. */
  save(id: string, input: SignInProviderInput): Promise<SignInProvider>;
  remove(id: string): Promise<void>;
  /** 422 `domain_unverified` with what DNS held; 409 `domain_taken` when another workspace verified it. Returns its provider. */
  verifyDomain(domain: string): Promise<SignInProvider>;
  /** The secret names an OIDC provider may give as `clientSecretRef`. */
  secretNames(): Promise<string[]>;
  /** Where a bank's identity provider reads the SAML service provider metadata; unset when no service serves it. */
  samlMetadataUrl?: string;
}
