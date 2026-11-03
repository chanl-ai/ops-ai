/** A connected system's sign-in, as tools-service serves it under /v1/connections (c-558). */

export type ConnectionEnvironment = 'test' | 'production';

/** Whose account a connection's calls sign in with: the team's, each person's own, or theirs with the team's as backup. */
export type SignInSetting = 'team' | 'person' | 'person_or_team';

export type ConnectionStatus = 'draft' | 'healthy' | 'needs_reconnect' | 'expiring' | 'revoked' | 'error';

/** Which account Test connection and a sign-in use: the caller's own, or the team's (admins only). */
export type SignInAccount = 'self' | 'team';

/** The last Test connection: whose account it signed in with, and what the system answered. */
export interface ConnectionHealth {
  status: 'ok' | 'failed';
  account: 'own' | 'team';
  environment: ConnectionEnvironment;
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

export interface ConnectionEnvironmentState {
  set: boolean;
  settings: Record<string, string>;
  secrets: Record<string, { set: boolean; setAt?: string | null; setBy?: string | null }>;
  signedIn?: SignedIn | null;
}

export interface ConnectionDetail {
  id: string;
  name: string;
  teamId: string;
  authKind: string;
  kindLabel: string;
  status: ConnectionStatus;
  statusDetail?: string | null;
  /** Absent on a kind that never signs in. */
  signIn?: SignInSetting;
  /** With `person_or_team`: a run with nobody behind it may use the team's account. */
  teamBackup?: boolean;
  health?: ConnectionHealth | null;
  mayManage: boolean;
  revision: number;
  environments: Record<string, ConnectionEnvironmentState>;
  environmentsSet: string[];
  usedBy: { id: string; name: string }[];
  /** Each person's own sign-in: an admin sees everyone's, anyone else their own. */
  people?: PersonSignedIn[];
  availableTo: string[];
  redirectUri?: string | null;
  updatedAt?: string | null;
}

export interface PersonSignedIn {
  personId: string;
  environment: ConnectionEnvironment;
  account?: string | null;
  scopes: string[];
  since?: string | null;
  expiresAt?: string | null;
}

/**
 * One of the caller's own sign-ins on a connection of their team (Your connections); with `every`, also a connection
 * they can connect themselves and have not (`connected` false, c-595).
 */
export interface MyConnection {
  /** The person's own account's last test after they signed in; null before any. */
  test?: { status: 'ok' | 'failed'; message?: string | null; at?: string } | null;
  connectionId: string;
  connection: string;
  connectionStatus: ConnectionStatus;
  environment: ConnectionEnvironment;
  /** How the person signs in: the kind's label, such as "API key". */
  method: string;
  authKind: string;
  /** What the person gives for a key, password or token kind; empty for a sign-in at the system. */
  personFields: string[];
  connected: boolean;
  /** Where the system says how to find the key. */
  docsUrl?: string | null;
  /** The system refused the person's key or sign-in: when and what it said; a new one clears it (c-595). */
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
  expiresAt?: string | null;
}

export interface AuthKind {
  id: string;
  label: string;
  signsIn: boolean;
  holdsToken: boolean;
  /** Whether each person may sign in with their own account; a kind without it offers the team's account only. */
  perPerson: boolean;
  /** The fields each person gives for themselves on a connection each person signs in to (c-595). */
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
  /** The environment the refused call ran in, where the person's own key belongs. */
  environment?: ConnectionEnvironment;
  /** The connection's kind and what each person gives for it (c-595): a key kind is asked for in a form, not a sign-in. */
  authKind?: string;
  personFields?: string[];
  connectUrl?: string;
  expiresAt?: string;
}

/** One row of Apps › Credentials: how one of the team's apps signs in, never its secret. */
export interface AppCredentialRow {
  /** The account the credential is set on. */
  id: string;
  name: string;
  /** The app as the Apps page names it: `plugin:<id>`, or a custom app's connection id. */
  app: string;
  appName: string;
  type: 'ops_ai' | 'own';
  permissions: string[];
  accounts: number;
  status: 'working' | 'not_tested' | 'failing';
  created: string;
}

/** The team's own OAuth client for one of its apps, as the New app credential window sends it. */
export interface AppCredentialInput {
  app: string;
  clientId: string;
  clientSecret: string;
  /** Among the app's own; left out, all of them. */
  scopes?: string[];
  environment?: ConnectionEnvironment;
}

/** Test with my account: whether signing in through the app credential worked, and as whom. */
export interface CredentialCheck {
  health: { status: 'ok' | 'failed'; account?: string | null; message?: string | null; environment: ConnectionEnvironment; at: string; by: string };
}
