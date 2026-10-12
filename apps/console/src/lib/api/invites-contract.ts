import type { InviteAcceptInput, InviteAcceptResult, InvitePreview } from '@/lib/types/invites';

/**
 * Invitation links. Public routes: the person opening the link is not signed in yet. Accepting creates the
 * account (password, or SSO when the email's domain is a verified SSO domain); signing in is the AuthProvider's.
 */
export interface InvitesApi {
  /** 404 for an unknown token. Expired and accepted invites still return, with their state, so the page can say so. */
  get(token: string): Promise<InvitePreview>;
  /** 410 when expired, 409 when already accepted, 400 when the password breaks the policy. */
  accept(token: string, input: InviteAcceptInput): Promise<InviteAcceptResult>;
}
