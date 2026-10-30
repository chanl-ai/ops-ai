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

/** One of the caller's own sign-ins on a connection of their team (Your connections). */
export interface MyConnection {
  connectionId: string;
  connection: string;
  connectionStatus: ConnectionStatus;
  environment: ConnectionEnvironment;
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
}

/**
 * What a `CONNECTION_NOT_LINKED` tool error carries in `details`: the connection to connect and the console page that
 * starts the sign-in (`/connections/connect?link=…`, single use, 15 minutes). `reason` says why: never connected, a
 * scope missing, or an operation that needs a person.
 */
export interface ConnectionRequired {
  connectionId: string;
  connection: string;
  reason: 'not_connected' | 'insufficient_scope' | 'needs_person';
  connectUrl?: string;
  expiresAt?: string;
}
