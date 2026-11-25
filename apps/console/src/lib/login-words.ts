// How a person meets an app's login, in one set of words: the admin's per-app setting, the chat's sign-in card, the
// line a team-login action shows, and what a Human Task waiting for a sign-in offers. The user guide uses the same
// words ("Everyone uses the team's login", "Each person signs in").

/** The values tools-service stores for an app's sign-in; the screen asks one question with two answers. */
export type SignInSetting = 'team' | 'person' | 'person_or_team';

/** The admin's answer for an app, as the app page, the agent's tools row and the Apps grid say it. */
export const signInChoiceWords = (value: SignInSetting): string => (value === 'team' ? 'Everyone uses the team’s login' : 'Each person signs in');

/** The chat card's title for an app each person signs in to, when the person has no login of their own yet. */
export const signInTitle = (app: string): string => `Sign in to ${app} to continue`;

interface SignedCall {
  server: string;
  signedIn?: { whose: 'team' | 'person'; login: string; app: string } | null;
}

// Servers that are the platform itself, never named to people (tool-call-card.tsx keeps the same list).
const INTERNAL = new Set(['workflows', 'Workflows', 'ops', 'kernel']);

/**
 * One line per app whose team login acted in a reply: who acted, and that the person is recorded as the one who asked.
 * Calls signed with the person's own login say nothing; they act as the person.
 */
export function teamLoginLines(calls: SignedCall[]): string[] {
  const seen = new Map<string, string>();
  for (const c of calls) {
    if (c.signedIn?.whose !== 'team') continue;
    const app = c.server && !INTERNAL.has(c.server) ? c.server : c.signedIn.app;
    const line = `Runs in ${app} as ${c.signedIn.login} (team login). You are recorded as the person who asked.`;
    if (!seen.has(app)) seen.set(app, line);
  }
  return [...seen.values()];
}

/**
 * What a Human Task waiting for someone's sign-in offers. The person it waits for only signs in: choosing between
 * their own login and the team's is the admin's per-app setting, never a question in a task. Someone else allowed to run
 * as the team's login (connections.run) may let the run go on with it.
 */
export function connectWaitActions(w: { mine: boolean; teamLogin: boolean; mayRunAsTeam: boolean }): ('sign_in' | 'run_as_team')[] {
  if (w.mine) return ['sign_in'];
  return w.teamLogin && w.mayRunAsTeam ? ['run_as_team'] : [];
}
