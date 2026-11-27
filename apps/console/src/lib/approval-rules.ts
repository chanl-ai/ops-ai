/**
 * Reading the team's approval rules as platform-service stores them. The one reader of `requesterMayDecide`'s shape is
 * `ops_access.policies.requester_may_decide`; this mirrors its contract for the console, with no area.
 */

const asMap = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});

/**
 * Whether whoever asked may approve their own request in `teamId`. A boolean holds for every team (a value stored
 * before the key was per team). Else `{team or '*': true, false or {area: bool}}`: the team's own part over the
 * workspace's `*`; a team with neither reads the default, on (the two-person rule off). A per-area part reads as on
 * when any area is on, so the page never shows the rule on while someone may approve their own request somewhere in
 * the team.
 */
export function requesterMayDecideOf(value: unknown, teamId: string): boolean {
  if (typeof value === 'boolean') return value;
  const held = asMap(value);
  if (!(teamId in held) && !('*' in held)) return true;
  const part = teamId in held ? held[teamId] : held['*'];
  if (typeof part === 'boolean') return part;
  return Object.values(asMap(part)).some((v) => v === true);
}

/**
 * Policies Governance › Policies does not list: the approval rules are set on Approvals (the old keys are derived from
 * them), and `approvalsFloor` has no editor until its own screen ships (the generic switch cannot send its object).
 */
const NOT_ON_POLICIES = new Set(['appChanges', 'appChangesByApp', 'toolWritesNeedApproval', 'appWritesNeedApproval', 'appsChangeWithoutAsking', 'requesterMayDecide', 'approvalsFloor']);

export const listedOnPolicies = (key: string) => !NOT_ON_POLICIES.has(key);

/** The team's makers' ask as saved (its part over the workspace's `*`), or null when neither stores one. */
export const makersAskOf = (saved: Record<string, unknown>): boolean | null => (typeof saved.makersAsk === 'boolean' ? saved.makersAsk : null);

/** Whether Approvals may save the makers' ask: only a choice, and one that differs from what is saved. Unset is never
 * saved as on or off for the admin: tools-service refuses the team's writes until they pick. */
export const makersAskSavable = (saved: boolean | null, chosen: boolean | null): boolean => chosen !== null && chosen !== saved;
