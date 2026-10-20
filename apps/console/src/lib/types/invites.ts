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
  /** Accepting signs the person in with no password to set here (platform-service, until SSO lands). */
  passwordless?: boolean;
  /** The email already has an account: that person accepts while signed in as themselves; the link alone never signs in. */
  existingAccount?: boolean;
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
  /** `session`: accepting already signed the person in. */
  authMethod: 'password' | 'sso' | 'session';
  /** Where to go next: the MFA enrolment page when required, else the overview. */
  next: string;
}
