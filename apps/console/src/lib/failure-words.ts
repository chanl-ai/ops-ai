// Why a tool call did not go through, in a person's words: one table for the chat's Connect card and every call log.
// The code stays on the call's details for whoever needs it; these words are what a row and a card say.

/** What a person reads for a failed call, by the gateway's error code; null for a code with no words of its own. */
const CALL_FAILURE: Record<string, string> = {
  CONNECTION_NOT_LINKED: 'Waited for the person’s own sign-in',
  NOT_SIGNED_IN: 'The account’s sign-in had ended',
  AUTH_EXPIRED: 'The account’s sign-in had ended',
  AUTH_FAILED: 'The app refused the account’s sign-in',
  CONNECTION_REVOKED: 'The account was disconnected',
  CONNECTION_NOT_SET: 'The app’s account is not set up',
  CONNECTION_MISSING: 'The app’s account no longer exists',
  ACCOUNT_NOT_FOUND: 'The app’s account no longer exists',
  CONNECTION_OUT_OF_SCOPE: 'The account belongs to another team',
  SECRET_MISSING: 'A secret the call needs is missing',
  SECRET_UNAVAILABLE: 'The secrets store did not answer',
  EGRESS_DENIED: 'Security has not allowed this address',
  RATE_LIMITED: 'The app asked to slow down',
  UPSTREAM_ERROR: 'The app answered with an error',
  UPSTREAM_TIMEOUT: 'The app did not answer in time',
  CONNECT_TIMEOUT: 'The app did not answer in time',
  POOL_TIMEOUT: 'The app did not answer in time',
  CONNECT_FAILED: 'The app could not be reached',
  TLS_FAILED: 'The app could not be reached securely',
  ANSWER_UNREADABLE: 'The app’s answer could not be read',
  PLUGIN_DISABLED: 'The app is not installed here',
  APP_OFF_FOR_TEAM: 'The app is turned off for this team',
  ACCOUNT_CHOICE_NEEDED: 'Waited for the person to choose an account',
  TOOL_NOT_ADDED: 'The tool is turned off for this team',
  INVALID_ARGUMENTS: 'The tool was given input it does not take',
  WRITE_IN_PROGRESS: 'The same change was already under way',
  CALL_ABANDONED: 'The call was abandoned',
};

/** The words for a failed call: its code's, else the gateway's own message, else a plain "The call failed". */
export function failureWords(code?: string | null, message?: string | null): string {
  return (code && CALL_FAILURE[code]) || message || 'The call failed';
}

/** The person-facing words for a sign-in a call waits on: the app and what the call does with their account. */
export type SignInNeed = { app: string; access?: 'read' | 'write' };

/** What the call does with the person's account, by its access: a read reads as them, a write changes in their name. */
export const actsAs = (need: SignInNeed) => (need.access === 'write' ? `This tool makes the change in ${need.app} in your name` : `This tool reads ${need.app} as you`);

/** A failed run's error in the one error model (the agents service's RunFailure). */
export type RunFailure = {
  kind: 'input' | 'refused' | 'upstream' | 'timeout' | 'internal';
  code: string;
  message: string;
  userMessage: string;
  retryable: boolean;
  nodeName?: string | null;
  nodeId?: string | null;
  attempt?: number | null;
  of?: number | null;
};

/** What failed, by its kind, so a reader sees at once whose move it is: the one set of words for a run and a reply. */
const KIND_WORDS: Record<RunFailure['kind'], (what: string) => string> = {
  input: (what) => `The ${what} could not use what it was given`,
  refused: (what) => `A rule stopped the ${what}`,
  upstream: (what) => `An app or model the ${what} uses failed`,
  timeout: (what) => `The ${what} ran out of time`,
  internal: (what) => `The ${what} stopped on an error on our side`,
};

export const failureKindWords = (kind: RunFailure['kind'], what: 'run' | 'reply') => KIND_WORDS[kind](what);

/** The run page's heading for a failure, by its kind. */
export const failureTitle = (f?: RunFailure | null) => (f ? failureKindWords(f.kind, 'run') : 'The run failed');

/** Where it failed and whether trying again helps, as one line under the message: `Find customer · attempt 3 of 3 · retrying may help`. */
export function failureWhere(f?: RunFailure | null): string {
  if (!f) return '';
  const step = f.nodeName || f.nodeId;
  const attempt = f.attempt ? (f.of ? `attempt ${f.attempt} of ${f.of}` : `attempt ${f.attempt}`) : '';
  return [step, attempt, f.retryable ? 'retrying may help' : 'retrying will not help until it is fixed'].filter(Boolean).join(' · ');
}
