/** Logo shown for a team in the switcher. */
export type TeamIcon = 'platform' | 'lending' | 'cards' | 'fraud' | 'onboarding' | 'retail' | 'wealth' | 'team';

/**
 * A bank team using Ops AI. The current team scopes every list, count and record the API returns:
 * a team sees records whose owner is one of its owner groups; a team with scope `all` sees everything.
 */
export interface Team {
  id: string;
  name: string;
  icon: TeamIcon;
  /** Owner values (as set on agents, workflows and sources) this team is responsible for. */
  ownerGroups: string[];
  scope: 'all' | 'owned';
  memberCount: number;
}

export interface TeamInput {
  name: string;
  ownerGroup: string;
}

/** Sent with a 403 when a record exists but belongs to a team other than the current one. */
export type TeamRef = Pick<Team, 'id' | 'name'>;
