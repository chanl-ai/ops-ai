/**
 * What the shell's gate decides before any page loads (c-505), as plain functions so a test can hold them.
 */

/**
 * The team requests go out for: the one this tab remembers when the person still holds it, else their own team, else
 * their first. Null while their teams are not known, so nothing is asked for a team they may not have. A team
 * remembered from someone who signed in before in this tab, or switched away from since, is not used.
 */
export function teamToUse(current: string, own: string | null, teams: readonly string[]): string | null {
  if (!teams.length) return null;
  if (teams.includes(current)) return current;
  if (own && teams.includes(own)) return own;
  return teams[0];
}

/** How a failed request reads to a person: one state per status, the same on every page. */
export type ErrorKind = 'signed_out' | 'forbidden' | 'not_found' | 'unavailable';

export function errorKind(error: unknown): ErrorKind {
  const status = (error as { status?: number } | null)?.status;
  if (status === 401) return 'signed_out';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  return 'unavailable';
}
