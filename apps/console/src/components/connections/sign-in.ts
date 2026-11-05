import * as React from 'react';
import { toast } from 'sonner';

import { sdk } from '@/lib/api/ops-sdk';
import type { AccountRef, SignInStart } from '@/lib/types/connections';
import type { OpsAI } from '@chanl-ai/ops-ai';

/** The message a sign-in's return page sends to the window that started it once the person is connected. */
export const CONNECTED_MESSAGE = 'ops:connection-signed-in';

export interface ConnectedMessage {
  type: typeof CONNECTED_MESSAGE;
  /** The sign-in's state, which names the one sign-in the message is about. */
  state?: string;
  connectionId: string;
  connection: string;
  account?: string | null;
}

/** The message the return page sends when access was refused or the sign-in failed. */
export const FAILED_MESSAGE = 'ops:connection-sign-in-failed';

export interface FailedMessage {
  type: typeof FAILED_MESSAGE;
  state?: string;
  message: string;
}

/**
 * The channel every console window of this site hears: the return page says on it how a sign-in ended. A sign-in
 * window that crossed a system's own pages may have lost its tie to the window that opened it (window.opener), so the
 * outcome travels on the channel as well as by postMessage.
 */
const CHANNEL = 'ops-sign-in';

/** Tells every window of the console how the sign-in under `state` ended, and the window that opened this one. */
export function announceSignIn(said: ConnectedMessage | FailedMessage): void {
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage(said);
    channel.close();
  } catch {
    // A browser without BroadcastChannel still has the opener.
  }
  const opener = window.opener as Window | null;
  if (opener && !opener.closed) opener.postMessage(said, window.location.origin);
}

/** Sends the window to the system's sign-in. Its state alone names the sign-in, so nothing is kept in the browser. */
export function goSignIn(start: SignInStart): void {
  window.location.assign(start.authorizeUrl);
}

/** Posted by the connect page once it listens, and by the opener to send it on to the system or to stop it. */
export const READY_MESSAGE = 'ops:sign-in-window-ready';
export const START_MESSAGE = 'ops:sign-in-start';
export const STOP_MESSAGE = 'ops:sign-in-stop';

export type WindowMessage = { type: typeof START_MESSAGE; start: SignInStart } | { type: typeof STOP_MESSAGE; message: string };

/** A sign-in window opened on the click, before the system's address is known. */
export interface SignInWindow {
  window: Window;
  /** Sends the window on to the system's sign-in for this account. */
  go(start: SignInStart, account: AccountRef): void;
  /** Shows the window's failure card with this reason; the person tries again or closes it. */
  fail(message: string): void;
  /** What Try again on the failure card runs: the same sign-in started again, sent on to this window. */
  retry(run: () => void): void;
}

const stateOf = (start: SignInStart) => new URL(start.authorizeUrl).searchParams.get('state') ?? '';

/**
 * Opens the connect page in a window of its own, synchronously in the click, so a pop-up blocker lets it through;
 * starting the sign-in takes calls first, and a window opened after an await is blocked. Each sign-in gets a window
 * of its own name, so an old sign-in window still open (from this stack or another) is never reused. The page waits
 * for `go`, which it receives once it says it is ready. Null, with a toast, when the browser blocked it.
 */
export function openSignInWindow(app: string, logo?: string | null): SignInWindow | null {
  const q = new URLSearchParams({ app, ...(logo && logo.length < 1500 ? { logo } : {}) });
  const name = `ops-sign-in-${Math.random().toString(36).slice(2)}`;
  const w = window.open(`/connections/connect?${q}`, name, 'popup,width=520,height=720');
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
    go: (start) => ((pending = { type: START_MESSAGE, start }), send()),
    fail: (message) => ((failed = true), (pending = { type: STOP_MESSAGE, message }), send()),
    retry: (run) => void (again = run),
  };
}

// A window that reads closed is given this long for the return page's word to arrive before it counts as closed early.
const CLOSED_GRACE_MS = 1500;
// How often the opener reads the account while a sign-in is out: the outcome still arrives when no word can (a sign-in
// finished in another browser, or a window the system's pages cut from its opener and from the channel).
const POLL_MS = 2000;

type Account = Awaited<ReturnType<OpsAI['raw']['tools']['apps_get_account']>>;

/** The newest sign-in the account holds, the team's or a person's, and who it signed in as. */
function newestSignIn(a: Account): { since: string; account: string | null } | null {
  const all = [a.signedIn, ...(a.people ?? [])].filter((x): x is NonNullable<typeof x> => Boolean(x?.since));
  const newest = all.sort((x, y) => String(y.since).localeCompare(String(x.since)))[0];
  return newest ? { since: String(newest.since), account: newest.account ?? null } : null;
}

/**
 * The opener's side of a sign-in window: `open` on the click, and the outcome, connected or failed, reaches the
 * callbacks for the sign-in this page started, by the channel, by postMessage, or by a read of the account that shows
 * a sign-in newer than the one it held when this one went out. Connected closes the window. A window closed before
 * the sign-in ended calls `onClosed`; a word that still arrives after that is delivered as usual.
 */
export function useSignInWindow(handlers: { onConnected?: (m: ConnectedMessage) => void; onFailed?: (message: string) => void; onClosed?: () => void }) {
  const current = React.useRef<SignInWindow | null>(null);
  const state = React.useRef<string | null>(null);
  // Set once the sign-in under `state` failed: the person closing the window then is not a sign-in closed early.
  const failed = React.useRef(false);
  const poll = React.useRef<number | null>(null);
  const latest = React.useRef(handlers);
  React.useEffect(() => {
    latest.current = handlers;
  });
  const stopPoll = React.useCallback(() => {
    if (poll.current !== null) window.clearInterval(poll.current);
    poll.current = null;
  }, []);
  const deliver = React.useCallback(
    (said: ConnectedMessage | FailedMessage | undefined) => {
      if (!said || !state.current || said.state !== state.current) return;
      if (said.type === CONNECTED_MESSAGE) {
        const w = current.current?.window;
        current.current = null;
        state.current = null;
        stopPoll();
        if (w && !w.closed) w.close();
        latest.current.onConnected?.(said);
      } else if (said.type === FAILED_MESSAGE) {
        // The window stays this page's: Try again in it may still connect.
        failed.current = true;
        latest.current.onFailed?.(said.message);
      }
    },
    [stopPoll],
  );
  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage | FailedMessage>) => {
      if (e.origin === window.location.origin) deliver(e.data);
    };
    window.addEventListener('message', onMessage);
    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel(CHANNEL);
      channel.onmessage = (e: MessageEvent<ConnectedMessage | FailedMessage>) => deliver(e.data);
    } catch {
      // The opener's postMessage and the account poll still arrive.
    }
    // A window closed before any word arrived: the person closed it, or it never reached the return page.
    const watch = window.setInterval(() => {
      const w = current.current?.window;
      if (!w || !w.closed || !state.current) return;
      const asked = state.current;
      window.setTimeout(() => {
        if (state.current !== asked || current.current?.window !== w) return;
        current.current = null;
        state.current = null;
        stopPoll();
        if (!failed.current) latest.current.onClosed?.();
      }, CLOSED_GRACE_MS);
    }, 500);
    return () => {
      window.removeEventListener('message', onMessage);
      channel?.close();
      window.clearInterval(watch);
      stopPoll();
    };
  }, [deliver, stopPoll]);
  /** Reads the account until it holds a sign-in newer than the one it held when this sign-in went out. */
  const watchAccount = React.useCallback(
    (asked: string, ref: AccountRef) => {
      stopPoll();
      const read = () => sdk((ops) => ops.raw.tools.apps_get_account({ path: { app_id: ref.appId, account_id: ref.accountId } }));
      // Undefined until the first read answers; a failed first read is tried again, never taken as "none".
      let before: string | null | undefined;
      const baseline = () => void read().then((a) => (before = newestSignIn(a)?.since ?? null), () => undefined);
      baseline();
      poll.current = window.setInterval(() => {
        if (state.current !== asked) return;
        if (before === undefined) return baseline();
        void read()
          .then((a) => {
            const now = newestSignIn(a);
            if (now && now.since !== before) deliver({ type: CONNECTED_MESSAGE, state: asked, connectionId: ref.accountId, connection: a.name, account: now.account });
          })
          .catch(() => undefined);
      }, POLL_MS);
    },
    [deliver, stopPoll],
  );
  const open = React.useCallback(
    (app: string, logo?: string | null) => {
      const w = openSignInWindow(app, logo);
      if (!w) return null;
      state.current = null;
      failed.current = false;
      stopPoll();
      // The state this sign-in goes out with, so only its own outcome is delivered here.
      const wrapped: SignInWindow = {
        ...w,
        go: (start, account) => {
          const asked = stateOf(start);
          state.current = asked;
          failed.current = false;
          watchAccount(asked, account);
          w.go(start, account);
        },
      };
      current.current = wrapped;
      return wrapped;
    },
    [stopPoll, watchAccount],
  );
  const close = React.useCallback(() => {
    current.current?.window.close();
    current.current = null;
    state.current = null;
    stopPoll();
  }, [stopPoll]);
  return { open, close, current };
}
