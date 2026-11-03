import * as React from 'react';
import { toast } from 'sonner';

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
export function goSignIn(start: SignInStart, connectionId: string, opts: { check?: boolean } = {}): void {
  remember(start, connectionId, Boolean(opts.check));
  window.location.assign(start.authorizeUrl);
}

/** `check` marks Test with my account, which the return page finishes as a test of the app credential, not a sign-in. */
function remember(start: SignInStart, connectionId: string, check: boolean): void {
  const state = new URL(start.authorizeUrl).searchParams.get('state') ?? '';
  try {
    sessionStorage.setItem(key(state), JSON.stringify({ connectionId, check }));
  } catch {
    // Without session storage the return page asks the person to start again.
  }
}

function remembered(state: string): { connectionId: string; check: boolean } | null {
  try {
    const raw = sessionStorage.getItem(key(state));
    if (!raw) return null;
    const v = JSON.parse(raw) as { connectionId?: string; check?: boolean };
    return v.connectionId ? { connectionId: v.connectionId, check: Boolean(v.check) } : null;
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

export type WindowMessage = { type: typeof START_MESSAGE; start: SignInStart; connectionId: string; check?: boolean } | { type: typeof STOP_MESSAGE; message: string };

/** A sign-in window opened on the click, before the system's address is known. */
export interface SignInWindow {
  window: Window;
  /** Sends the window on to the system's sign-in; `check` makes it Test with my account. */
  go(start: SignInStart, connectionId: string, opts?: { check?: boolean }): void;
  /** Shows the window's failure card with this reason; the person closes it. */
  fail(message: string): void;
}

/**
 * Opens the connect page in a window of its own, synchronously in the click, so a pop-up blocker lets it through;
 * starting the sign-in takes calls first, and a window opened after an await is blocked. The page waits for `go`,
 * which it receives once it says it is ready, and keeps the connection's id in its own session. Null, with a toast,
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
  let pending: WindowMessage | null = null;
  const send = () => {
    if (!ready || !pending) return;
    w.postMessage(pending, window.location.origin);
    pending = null;
    window.removeEventListener('message', onReady);
  };
  const onReady = (e: MessageEvent<{ type?: string }>) => {
    if (e.origin !== window.location.origin || e.source !== w || e.data?.type !== READY_MESSAGE) return;
    ready = true;
    send();
  };
  window.addEventListener('message', onReady);
  return {
    window: w,
    go: (start, connectionId, opts) => ((pending = { type: START_MESSAGE, start, connectionId, check: opts?.check }), send()),
    fail: (message) => ((pending = { type: STOP_MESSAGE, message }), send()),
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
        current.current = null;
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

/** The connection a returning state was sent out for. */
export function signInFor(state: string): string | null {
  return remembered(state)?.connectionId ?? null;
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
