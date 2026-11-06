/**
 * Whether a failed call means the services could not answer (no response at all, or a 5xx), rather than an answer
 * such as 401, 403 or 404. The shell and sign-in say the same thing for it, so an outage reads as one state.
 */
export function isUnreachable(e: unknown): boolean {
  const status = (e as { status?: number } | null)?.status;
  // A sign-in refusal is an answer (a wrong password, an empty email) unless the service sent a 5xx; only a call that
  // got no response at all carries no status.
  if ((e as Error | null)?.name === 'AuthError') return (status ?? 0) >= 500;
  return !!e && (status === undefined || status >= 500);
}

export const UNREACHABLE = 'Ops AI can’t reach its services right now. Try again in a moment.';

/** A read as the shell sees it: how many show it, its state, and whether it is a side read (`meta.side`). */
export interface ShownRead {
  observers: number;
  status: string;
  error: unknown;
  failures: number;
  failureReason: unknown;
  /** A read only a part of the page needs (a dialog's options): its own place says when it fails. */
  side: boolean;
}

/**
 * Whether the page-wide "can't reach its services" banner shows: a read on screen failed because the services did not
 * answer, from its first failed try until one succeeds. A side read never raises it.
 */
export function servicesDown(reads: ShownRead[]): boolean {
  return reads.some(
    (q) =>
      q.observers > 0 &&
      !q.side &&
      ((q.status === 'error' && isUnreachable(q.error)) || (q.failures > 0 && isUnreachable(q.failureReason))),
  );
}
