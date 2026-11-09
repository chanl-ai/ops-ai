/** One person who may do something in the team, as GET /v1/access/holders answers them. */
export interface Holder {
  name: string;
  email: string;
  /** Granted in this team itself, not only by a grant in every team (a workspace admin's, or the install's first). */
  inTeam?: boolean;
}

/**
 * Whom an "Ask an admin" line names: the first person granted in the team itself, never the caller, with how many more
 * may; with nobody granted in the team, no name, so a grant in every team (the install's first admin) is never named
 * and the line says to ask the team's admins.
 */
export function askWhom(holders: Holder[], me?: string): { first: Holder | null; more: number; all: Holder[] } {
  const others = holders.filter((h) => h.email.toLowerCase() !== (me ?? '').toLowerCase());
  const here = others.filter((h) => h.inTeam);
  return { first: here[0] ?? null, more: Math.max(0, here.length - 1), all: here.length ? here : others };
}
