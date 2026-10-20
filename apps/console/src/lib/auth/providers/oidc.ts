import type { AuthProvider } from '../provider';
import { unconfigured } from './unconfigured';

/** OpenID Connect against the bank's IdP (authorisation code with PKCE). Not wired yet. */
export const createOidcProvider = (): AuthProvider => unconfigured('oidc', 'NEXT_PUBLIC_OIDC_ISSUER and NEXT_PUBLIC_OIDC_CLIENT_ID');
