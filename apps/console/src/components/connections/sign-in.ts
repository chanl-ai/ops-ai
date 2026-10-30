import type { SignInStart } from '@/lib/types/connections';

/** The message the sign-in window posts to the chat that opened it once the person is connected. */
export const CONNECTED_MESSAGE = 'ops:connection-signed-in';

export interface ConnectedMessage {
  type: typeof CONNECTED_MESSAGE;
  connectionId: string;
  connection: string;
  account?: string | null;
}

const key = (state: string) => `ops-sign-in:${state}`;

/**
 * Sends the window to the system's sign-in. The system returns to one fixed page with only a code and a state, while
 * finishing needs the connection's id, so the id is kept in this window's session under the state it goes out with.
 */
export function goSignIn(start: SignInStart, connectionId: string): void {
  remember(start, connectionId);
  window.location.assign(start.authorizeUrl);
}

function remember(start: SignInStart, connectionId: string): void {
  const state = new URL(start.authorizeUrl).searchParams.get('state') ?? '';
  try {
    sessionStorage.setItem(key(state), connectionId);
  } catch {
    // Without session storage the return page asks the person to start again.
  }
}

/**
 * Opens the system's sign-in in a window of its own from a page that started it. A window opened this way starts with
 * a copy of this tab's session, so the id kept here first is there when the system returns.
 */
export function openSignIn(start: SignInStart, connectionId: string): Window | null {
  remember(start, connectionId);
  return window.open(start.authorizeUrl, 'ops-sign-in', 'popup,width=520,height=720');
}

/** The connection a returning state was sent out for. */
export function signInFor(state: string): string | null {
  try {
    return sessionStorage.getItem(key(state));
  } catch {
    return null;
  }
}

/** Forgets a state once its sign-in finished; the service refuses a state used twice anyway. */
export function forgetSignIn(state: string): void {
  try {
    sessionStorage.removeItem(key(state));
  } catch {
    // Nothing kept.
  }
}
