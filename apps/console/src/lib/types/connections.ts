/** An app's account and its sign-ins, as tools-service serves them under /v1/apps and /v1/me/accounts. */

/** One app's account, as every account route addresses it: the app's id (`plugin:<id>`, or a custom app's) and its own. */
export interface AccountRef {
  appId: string;
  accountId: string;
}

/** Whose account a connection's calls sign in with: the team's, each person's own, or theirs with the team's as backup. */
export type SignInSetting = 'team' | 'person' | 'person_or_team';

export type ConnectionStatus = 'draft' | 'healthy' | 'needs_reconnect' | 'expiring' | 'revoked' | 'error';

/** Which account Test connection and a sign-in use: the caller's own, or the team's (admins only). */
export type SignInAccount = 'self' | 'team';

/** The last Test connection: whose account it signed in with, and what the system answered. */
export interface ConnectionHealth {
  status: 'ok' | 'failed';
  account: 'own' | 'team';
  at: string;
  by: string;
  code?: string | null;
  httpStatus?: number | null;
  latencyMs?: number | null;
  message?: string | null;
}

export interface SignedIn {
  account?: string | null;
  scopes: string[];
  since?: string | null;
  expiresAt?: string | null;
}

/** What the system sent back to the return page: the state with the code, or with the error it refused with. */
export interface SignInReturn {
  state: string;
  code?: string;
  error?: string;
  errorDescription?: string;
}

/** A finished sign-in: its account and app, and the account signed in or, for Test with my account, the check. */
export interface SignInFinished {
  appId: string;
  accountId: string;
  check: boolean;
  account?: { id: string; name: string } | null;
  health?: CredentialCheck['health'] | null;
}

export interface PersonSignedIn {
  personId: string;
  account?: string | null;
  scopes: string[];
  since?: string | null;
  expiresAt?: string | null;
}

/**
 * One of the caller's own sign-ins on a connection of their team (Your connections); with `every`, also a connection
 * they can connect themselves and have not (`connected` false).
 */
export interface MyConnection {
  /** The person's own account's last test after they signed in; null before any. */
  test?: { status: 'ok' | 'failed'; message?: string | null; at?: string } | null;
  connectionId: string;
  /** The account's app, which starting its sign-in needs. */
  appId?: string | null;
  /** The app's name and logo, as the Apps grid shows them; `connection` names the account. */
  app: string;
  logo?: string | null;
  connection: string;
  connectionStatus: ConnectionStatus;
  /** The app's sandbox account, which only test runs use. */
  sandbox: boolean;
  /** How the person signs in: the kind's label, such as "API key". */
  method: string;
  authKind: string;
  /** What the person gives for a key, password or token kind; empty for a sign-in at the system. */
  personFields: string[];
  connected: boolean;
  /** Where the system says how to find the key. */
  docsUrl?: string | null;
  /** The system refused the person's key or sign-in: when and what it said; a new one clears it. */
  refused?: boolean;
  refusedAt?: string | null;
  refusedReason?: string | null;
  account?: string | null;
  scopes: string[];
  since?: string | null;
  expiresAt?: string | null;
}

/** Where to send the person to sign in; the system returns them to `redirectUri` with a code and state. */
export interface SignInStart {
  authorizeUrl: string;
  redirectUri: string;
  connectionId?: string | null;
  /** The account's app, which finishing the sign-in needs. */
  appId?: string | null;
  expiresAt?: string | null;
}

export interface AuthKind {
  id: string;
  label: string;
  signsIn: boolean;
  holdsToken: boolean;
  /** Whether each person may sign in with their own account; a kind without it offers the team's account only. */
  perPerson: boolean;
  /** The fields each person gives for themselves on a connection each person signs in to. */
  personFields?: string[];
  /** Each field's name, label and whether it is secret, as the service names them. */
  fields?: { name: string; label: string; secret: boolean; help?: string | null }[];
}

/**
 * What a `CONNECTION_NOT_LINKED` tool error carries in `details`: the connection to connect and the console page that
 * starts the sign-in (`/connections/connect?link=…`, single use, 15 minutes). `reason` says why: never connected, a
 * scope missing, or an operation that needs a person.
 */
/**
 * Why tools-service refused a call with `CONNECTION_NOT_LINKED` (auth/__init__.py NotLinkedReason): never connected, a
 * scope missing, an operation that needs a person, a call with nobody behind it, or the system refused the person's
 * own key or sign-in. Kept equal to the service's list
 * by services/tools-service/tests/test_person_credentials.py.
 */
export const CONNECTION_REQUIRED_REASONS = ['not_connected', 'insufficient_scope', 'needs_person', 'no_person', 'refused'] as const;
export type ConnectionRequiredReason = (typeof CONNECTION_REQUIRED_REASONS)[number];

export interface ConnectionRequired {
  connectionId: string;
  connection: string;
  reason: ConnectionRequiredReason;
  /** The connection's kind and what each person gives for it: a key kind is asked for in a form, not a sign-in. */
  authKind?: string;
  personFields?: string[];
  connectUrl?: string;
  expiresAt?: string;
}

/** Test with my account: whether signing in through the app credential worked, and as whom. */
interface CredentialCheck {
  health: { status: 'ok' | 'failed'; account?: string | null; message?: string | null; at: string; by: string };
}
