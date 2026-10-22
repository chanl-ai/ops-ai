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
