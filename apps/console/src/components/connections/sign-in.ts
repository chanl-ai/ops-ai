import * as React from 'react';
import { toast } from 'sonner';

import type { AccountRef, SignInStart } from '@/lib/types/connections';

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
 * finishing needs the account and its app, so both are kept in this window's session under the state it goes out with.
 */
export function goSignIn(start: SignInStart, account: AccountRef, opts: { check?: boolean } = {}): void {
  remember(start, account, Boolean(opts.check));
  window.location.assign(start.authorizeUrl);
}

/** `check` marks Test with my account, which the return page finishes as a test of the app credential, not a sign-in. */
function remember(start: SignInStart, account: AccountRef, check: boolean): void {
  const state = new URL(start.authorizeUrl).searchParams.get('state') ?? '';
  try {
    sessionStorage.setItem(key(state), JSON.stringify({ ...account, check }));
  } catch {
    // Without session storage the return page asks the person to start again.
  }
}

function remembered(state: string): (AccountRef & { check: boolean }) | null {
  try {
    const raw = sessionStorage.getItem(key(state));
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<AccountRef> & { check?: boolean };
    return v.appId && v.accountId ? { appId: v.appId, accountId: v.accountId, check: Boolean(v.check) } : null;
  } catch {
    return null;
  }
}

/** The message the sign-in window posts to the page that opened it when access was refused or the sign-in failed. */
export const FAILED_MESSAGE = 'ops:connection-sign-in-failed';

export interface FailedMessage {
  type: typeof FAILED_MESSAGE;
  message: string;
}

/** Posted by the connect page once it listens, and by the opener to send it on to the system or to stop it. */
export const READY_MESSAGE = 'ops:sign-in-window-ready';
export const START_MESSAGE = 'ops:sign-in-start';
export const STOP_MESSAGE = 'ops:sign-in-stop';

export type WindowMessage = { type: typeof START_MESSAGE; start: SignInStart; account: AccountRef; check?: boolean } | { type: typeof STOP_MESSAGE; message: string };

/** A sign-in window opened on the click, before the system's address is known. */
export interface SignInWindow {
  window: Window;
  /** Sends the window on to the system's sign-in; `check` makes it Test with my account. */
  go(start: SignInStart, account: AccountRef, opts?: { check?: boolean }): void;
  /** Shows the window's failure card with this reason; the person tries again or closes it. */
  fail(message: string): void;
  /** What Try again on the failure card runs: the same sign-in started again, sent on to this window. */
  retry(run: () => void): void;
}

/**
 * Opens the connect page in a window of its own, synchronously in the click, so a pop-up blocker lets it through;
 * starting the sign-in takes calls first, and a window opened after an await is blocked. The page waits for `go`,
 * which it receives once it says it is ready, and keeps the account's ids in its own session. Null, with a toast,
 * when the browser blocked it.
 */
export function openSignInWindow(app: string, logo?: string | null): SignInWindow | null {
  const q = new URLSearchParams({ app, ...(logo && logo.length < 1500 ? { logo } : {}) });
  const w = window.open(`/connections/connect?${q}`, 'ops-sign-in', 'popup,width=520,height=720');
  if (!w) {
    toast.error('The sign-in window was blocked', { description: 'Allow pop-ups for this site, then try again.' });
    return null;
  }
  let ready = false;
  let failed = false;
  let pending: WindowMessage | null = null;
  let again: (() => void) | null = null;
  const send = () => {
    if (!ready || !pending) return;
    w.postMessage(pending, window.location.origin);
    pending = null;
  };
  // The window says it is ready when it first loads, and again when Try again reloads it after a failure; the second
  // time starts the sign-in again in the same window, so no new pop-up is needed.
  const onReady = (e: MessageEvent<{ type?: string }>) => {
    if (e.origin !== window.location.origin || e.source !== w) return;
    // A refusal on the app's own page, or a sign-in that did not finish, also lets Try again start it once more.
    if (e.data?.type === FAILED_MESSAGE) failed = true;
    if (e.data?.type !== READY_MESSAGE) return;
    ready = true;
    if (failed && again) {
      failed = false;
      again();
      return;
    }
    send();
  };
  window.addEventListener('message', onReady);
  return {
    window: w,
    go: (start, account, opts) => ((pending = { type: START_MESSAGE, start, account, check: opts?.check }), send()),
    fail: (message) => ((failed = true), (pending = { type: STOP_MESSAGE, message }), send()),
    retry: (run) => void (again = run),
  };
}

/**
 * The opener's side of a sign-in window: `open` on the click, and the window's answer, connected or failed, reaches
 * the callbacks only from the window this page opened.
 */
export function useSignInWindow(handlers: { onConnected?: (m: ConnectedMessage) => void; onFailed?: (message: string) => void }) {
  const current = React.useRef<SignInWindow | null>(null);
  const latest = React.useRef(handlers);
  React.useEffect(() => {
    latest.current = handlers;
  });
  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage | FailedMessage>) => {
      if (e.origin !== window.location.origin || !current.current || e.source !== current.current.window) return;
      if (e.data?.type === CONNECTED_MESSAGE) {
        current.current = null;
        latest.current.onConnected?.(e.data);
      } else if (e.data?.type === FAILED_MESSAGE) {
        // The window stays this page's: Try again in it may still connect.
        latest.current.onFailed?.(e.data.message);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);
  const open = React.useCallback((app: string, logo?: string | null) => (current.current = openSignInWindow(app, logo)), []);
  const close = React.useCallback(() => {
    current.current?.window.close();
    current.current = null;
  }, []);
  return { open, close, current };
}

const APP_KEY = 'ops-sign-in:app';

/** Keeps the app this window connects, so a failed return can open the connect page for it again. */
export function rememberSignInApp(app: string, logo: string | null): void {
  try {
    sessionStorage.setItem(APP_KEY, JSON.stringify({ app, logo }));
  } catch {
    // Try again then names no app.
  }
}

/** The connect page address for the app this window was opened for; its load starts the sign-in again. */
export function retrySignInHref(): string {
  let kept: { app?: string; logo?: string | null } = {};
  try {
    kept = JSON.parse(sessionStorage.getItem(APP_KEY) ?? '{}') as typeof kept;
  } catch {
    // Nothing kept.
  }
  const q = new URLSearchParams({ app: kept.app || 'the app', ...(kept.logo ? { logo: kept.logo } : {}) });
  return `/connections/connect?${q}`;
}

/** The account a returning state was sent out for. */
export function signInFor(state: string): AccountRef | null {
  const r = remembered(state);
  return r ? { appId: r.appId, accountId: r.accountId } : null;
}

/** Whether a returning state was Test with my account. */
export function signInIsCheck(state: string): boolean {
  return remembered(state)?.check ?? false;
}

/** Forgets a state once its sign-in finished; the service refuses a state used twice anyway. */
export function forgetSignIn(state: string): void {
  try {
    sessionStorage.removeItem(key(state));
  } catch {
    // Nothing kept.
  }
}
