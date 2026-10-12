/** An invitation link: who invited whom into which team, with what role, and what sign-in the email gets. */

export type InviteState = 'pending' | 'expired' | 'accepted';

export interface InvitePreview {
  token: string;
  email: string;
  team: string;
  role: string;
  invitedBy: string;
  invitedAt: string;
  expiresAt: string;
  state: InviteState;
  /** True when the email's domain is a verified SSO domain: the person continues with SSO instead of a password. */
  sso: boolean;
  ssoProviderLabel?: string;
  /** Workspace policy at accept time: MFA enrolment follows when required. */
  mfaRequired: boolean;
}

export interface InviteAcceptInput {
  name: string;
  /** Password accounts only. */
  password?: string;
}

export interface InviteAcceptResult {
  email: string;
  name: string;
  team: string;
  authMethod: 'password' | 'sso';
  /** Where to go next: the MFA enrolment page when required, else the overview. */
  next: string;
}
