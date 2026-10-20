import { chosenTeamId, currentTeamId, setOwnTeam } from './team-context';

/** A person signed in for real: the access token every service accepts, and the teams it names. */
export interface SignedInIdentity {
  token: string;
  teamIds: string[];
}

interface IdentitySource {
  current(): SignedInIdentity | null;
  /** A fresh token after a 401 (expired while the tab slept); null when the session is over. */
  renew(): Promise<SignedInIdentity | null>;
}

let source: IdentitySource | null = null;

/**
 * Where the signed-in person's token comes from. Set once, in `@/lib/api`, when the sign-in adapter issues real
 * tokens (platform); the mock adapter issues none, so no Authorization header is sent and services fall back to
 * their dev identity.
 */
export function setIdentitySource(next: IdentitySource) {
  source = next;
  setOwnTeam(() => next.current()?.teamIds[0] ?? null);
}

/**
 * The headers every call to an Ops AI service carries. Signed in for real with no team picked yet, the console's
 * default team is not one of the person's, so the token's first team is sent. A picked team is sent as picked: one the
 * token no longer names answers 403 team_forbidden, which shows a stale choice instead of writing to another team.
 */
export function identityHeaders(): Record<string, string> {
  const id = source?.current();
  if (!id) return { 'X-Team-Id': currentTeamId() };
  const team = chosenTeamId() ?? id.teamIds[0];
  return team ? { 'X-Team-Id': team, Authorization: `Bearer ${id.token}` } : { Authorization: `Bearer ${id.token}` };
}

/**
 * fetch with the identity headers; a 401 under a real sign-in renews the token once and retries. A call that went out
 * before another one renewed the token retries with the newer token instead of renewing again.
 */
export async function fetchWithIdentity(url: string, init: RequestInit & { headers?: Record<string, string> } = {}): Promise<Response> {
  const send = () => fetch(url, { ...init, headers: { ...init.headers, ...identityHeaders() } });
  const sentWith = source?.current()?.token;
  const res = await send();
  if (res.status !== 401 || !sentWith || init.signal?.aborted) return res;
  if (source?.current()?.token !== sentWith) return send();
  return (await source!.renew()) ? send() : res;
}
