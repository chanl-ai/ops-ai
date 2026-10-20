/**
 * Whether a failed call means the services could not answer (no response at all, or a 5xx), rather than an answer
 * such as 401, 403 or 404. The shell and sign-in say the same thing for it, so an outage reads as one state.
 */
export function isUnreachable(e: unknown): boolean {
  const status = (e as { status?: number } | null)?.status;
  return !!e && (status === undefined || status >= 500);
}

export const UNREACHABLE = 'Ops AI can’t reach its services right now. Try again in a moment.';
