import type { AuthKind, ConnectionDetail, ConnectionEnvironment, MyConnection, SignInAccount, SignInSetting, SignInStart } from '@/lib/types/connections';

/**
 * A connected system's sign-in (tools-service, c-558): whose account its calls use, Test connection, and each person's
 * own sign-in. Every call acts in the current team, the only team whose connections it sees.
 */
export interface ConnectionsApi {
  get(id: string): Promise<ConnectionDetail>;
  /** Which kinds sign in at all; a kind that never signs in offers no sign-in setting. */
  kinds(): Promise<AuthKind[]>;
  /** Admins only. `revision` is the connection's as read; a stale one is refused with 409. */
  setSignIn(id: string, input: { revision: number; signIn: SignInSetting; teamBackup?: boolean }): Promise<ConnectionDetail>;
  /** Signs in with `account` and calls the connection's test address; the result is kept as the connection's health. */
  test(id: string, input: { environment: ConnectionEnvironment; account?: SignInAccount }): Promise<ConnectionDetail>;
  /** Where to send the person to sign in with `account` (their own unless they manage the connection and ask for the team's). */
  startSignIn(id: string, input: { environment: ConnectionEnvironment; account?: SignInAccount }): Promise<SignInStart>;
  /** Finishes a sign-in with the code and state the system returned; only the person who started it may. */
  completeSignIn(id: string, input: { code: string; state: string }): Promise<ConnectionDetail>;
  /** Starts the sign-in a `CONNECTION_NOT_LINKED` link names; 404 once used or expired, 403 for anyone else. */
  openConnectLink(link: string): Promise<SignInStart>;
  /** The caller's own sign-ins on this team's connections (Your connections). */
  mine(): Promise<MyConnection[]>;
  /** Ends the caller's own sign-in, asking the system to revoke it; the next call asks them to connect again. */
  disconnect(id: string, environment: ConnectionEnvironment): Promise<void>;
}
