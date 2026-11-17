import type { OpsAI } from '@chanl-ai/ops-ai';

import type { Narrow } from './served';

type Platform = OpsAI['raw']['platform'];
type Reply<K extends keyof Platform> = Awaited<ReturnType<Platform[K]>>;
type Body<K extends keyof Platform> = NonNullable<NonNullable<Parameters<Platform[K]>[0]>['body']>;

/** Logo shown for a team in the switcher. */
export type TeamIcon = 'platform' | 'lending' | 'cards' | 'fraud' | 'onboarding' | 'retail' | 'wealth' | 'team';

/**
 * A bank team using Ops AI. The current team scopes every list, count and record the API returns:
 * a team sees records whose owner is one of its owner groups; a team with scope `all` sees everything.
 */
/** `role` (the signed-in person's role in the team) is returned too; no screen reads it. */
export type Team = Omit<Narrow<Reply<'teams_list_teams'>[number], { scope: 'all' | 'owned' }>, 'role'> & {
  /** Not returned by platform-service yet: the switcher derives it from the name. */
  icon: TeamIcon;
};

export interface TeamInput {
  name: string;
  ownerGroup: string;
}

/** Sent with a 403 when a record exists but belongs to a team other than the current one. */
export type TeamRef = Pick<Team, 'id' | 'name'>;

/** A team as a workspace admin sees it on Govern > Access > Teams; counts come from platform-service. */
export type WorkspaceTeam = Narrow<Reply<'teams_list_workspace_teams'>['data'][number], { scope: 'all' | 'owned' }>;

export type WorkspaceTeamFilters = {
  status?: WorkspaceTeam['status'][];
};

/** A new team and the email of the person who becomes its first admin. */
export type WorkspaceTeamInput = Body<'teams_create_team'>;
