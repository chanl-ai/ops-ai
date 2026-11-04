import type { AccountRef, AuthKind, CredentialCheck, MyConnection, SignedInAccount, SignInAccount, SignInStart } from '@/lib/types/connections';

/**
 * An app's account sign-ins (tools-service): starting and finishing one, each person's own sign-in, and the team's
 * own app credentials. Every call acts in the current team, the only team whose accounts it sees.
 */
export interface ConnectionsApi {
  /** Which kinds sign in at all; a kind that never signs in offers no sign-in setting. */
  kinds(): Promise<AuthKind[]>;
  /** Where to send the person to sign in with `account` (their own unless they manage the account and ask for the team's). */
  startSignIn(ref: AccountRef, input: { account?: SignInAccount }): Promise<SignInStart>;
  /** Finishes a sign-in with the code and state the system returned; only the person who started it may. */
  completeSignIn(ref: AccountRef, input: { code: string; state: string }): Promise<SignedInAccount>;
  /** Starts the sign-in a `CONNECTION_NOT_LINKED` link names; 404 once used or expired, 403 for anyone else. */
  openConnectLink(link: string): Promise<SignInStart>;
  /** The caller's own sign-ins on this team's accounts (My accounts); `every` adds those they can connect. */
  mine(every?: boolean): Promise<MyConnection[]>;
  /** The caller's own key, password or token on an account each person signs in to; never answered back. */
  giveOwn(id: string, input: { credentials: Record<string, string> }): Promise<MyConnection>;
  /** Ends the caller's own sign-in, asking the system to revoke it; the next call asks them to connect again. */
  disconnect(id: string): Promise<void>;
  /** Adds the team's own OAuth app to one of its apps; team admins only. 409 when the app takes no client or has one. */
  /** Test with my account: where the admin signs in through the app credential; nothing is kept but the result. */
  startCredentialCheck(ref: AccountRef): Promise<SignInStart>;
  /** Finishes Test with my account with the code and state the sign-in returned. */
  finishCredentialCheck(ref: AccountRef, input: { state: string; code: string }): Promise<CredentialCheck>;
}
