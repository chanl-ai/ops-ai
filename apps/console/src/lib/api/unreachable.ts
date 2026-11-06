/**
 * Whether a failed call means the services could not answer (no response at all, or a 5xx other than a 503 naming its cause),
 * rather than an answer such as 401, 403 or 404. The shell and sign-in say the same thing for it, so an outage reads as
 * one state.
 */
export function isUnreachable(e: unknown): boolean {
  const status = (e as { status?: number } | null)?.status;
  // A sign-in refusal is an answer (a wrong password, an empty email) unless the service sent a 5xx; only a call that
  // got no response at all carries no status.
  if ((e as Error | null)?.name === 'AuthError') return (status ?? 0) >= 500;
  return !!e && (status === undefined || (status >= 500 && !answeredOutage(e)));
}

/**
 * A 503 the service answered with its own error code (`models_unavailable`): it is up and says a part behind it is
 * down. Asking again at once or on a timer only repeats that answer, so such a read is asked once and its place says so.
 * Only a 503: an unhandled failure answers 500 with the code `internal`, and that stays an outage.
 */
export function answeredOutage(e: unknown): boolean {
  const { status, code } = (e ?? {}) as { status?: number; code?: unknown };
  return status === 503 && typeof code === 'string' && code.length > 0;
}

/**
 * Whether a failed read is asked again: an outage four times (1, 2, 4 then 8 seconds apart); a part behind a service
 * that says it is down, a 403 or a 404 never; anything else once, at once. Reads only: mutations never retry.
 */
export function retryRead(failures: number, e: unknown): boolean {
  if (isUnreachable(e)) return failures < 4;
  if (answeredOutage(e) || [403, 404].includes((e as { status?: number } | null)?.status ?? 0)) return false;
  return failures < 1;
}

/** How long a failed read stays failed for every part of the page that mounts after it, before one of them asks again. */
export const FAILED_READ_HOLD_MS = 30_000;

/**
 * Whether a part mounting on a failed read asks again. Within the hold it shares the failure, so a page whose five parts
 * read the same list makes one call in an outage, not one per part; after it, the next mount tries again.
 */
export function retryReadOnMount(state: { status: string; errorUpdatedAt: number }, now = Date.now()): boolean {
  return !(state.status === 'error' && now - state.errorUpdatedAt < FAILED_READ_HOLD_MS);
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
