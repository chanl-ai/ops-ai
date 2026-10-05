import type { Team, TeamInput } from '@/lib/types/team';

import { ApiError } from '../contract';
import { currentTeamId, DEFAULT_TEAM_ID } from '../team-context';
import { id, respond } from './runtime';

/**
 * Teams and the scoping every mock list applies. Owner groups include the knowledge-source owners each team
 * answers for (Branch Network and Customer Care sit under Retail Banking), so their sources follow the team.
 */
const teams: Team[] = [
  { id: DEFAULT_TEAM_ID, name: 'Platform', icon: 'platform', ownerGroups: [], scope: 'all', memberCount: 6 },
  { id: 'team_lending', name: 'Lending Ops', icon: 'lending', ownerGroups: ['Lending Ops'], scope: 'owned', memberCount: 14 },
  { id: 'team_cards', name: 'Card Services', icon: 'cards', ownerGroups: ['Card Services'], scope: 'owned', memberCount: 22 },
  { id: 'team_fraud', name: 'Fraud Strategy', icon: 'fraud', ownerGroups: ['Fraud Strategy', 'Fraud Operations', 'Financial Crime Ops'], scope: 'owned', memberCount: 11 },
  { id: 'team_onboarding', name: 'Onboarding', icon: 'onboarding', ownerGroups: ['Onboarding'], scope: 'owned', memberCount: 9 },
  { id: 'team_retail', name: 'Retail Banking', icon: 'retail', ownerGroups: ['Retail Banking', 'Retail Product', 'Branch Network', 'Customer Care'], scope: 'owned', memberCount: 31 },
  { id: 'team_wealth', name: 'Wealth', icon: 'wealth', ownerGroups: ['Wealth'], scope: 'owned', memberCount: 7 },
];

const current = () => teams.find((t) => t.id === currentTeamId()) ?? teams[0];
/** Synchronous team lookups for mocks that report per team (usage, members, audit). Owners outside every team fall to Platform. */
export const teamDirectory = { current, all: () => teams, ofOwner: (owner?: string) => teams.find((t) => t.scope === 'owned' && !!owner && t.ownerGroups.includes(owner)) ?? teams[0] };

/** True when the current team may see a record with any of these owners. */
export function inTeam(owners: string | (string | undefined)[] | undefined): boolean {
  const t = current();
  if (t.scope === 'all') return true;
  return [owners].flat().some((o) => !!o && t.ownerGroups.includes(o));
}

/** The owner group new records get when created inside a team; undefined for Platform. */
export const teamOwner = (): string | undefined => (current().scope === 'all' ? undefined : current().ownerGroups[0]);

/** Throws a 403 naming the owning team when the record is outside the current one. */
export function guardTeam(owners: string | (string | undefined)[] | undefined, what: string) {
  if (inTeam(owners)) return;
  const list = [owners].flat();
  const owner = teams.find((t) => t.scope === 'owned' && list.some((o) => !!o && t.ownerGroups.includes(o))) ?? teams[0];
  throw new ApiError(`This ${what} belongs to ${owner.name}.`, 403, { id: owner.id, name: owner.name });
}

export const teamsApi = {
  list: () => respond(() => teams),
  create: (input: TeamInput) =>
    respond(() => {
      const name = input.name.trim();
      if (!name) throw new ApiError('Name the team.', 400);
      if (teams.some((t) => t.name.toLowerCase() === name.toLowerCase())) throw new ApiError(`A team named ${name} already exists.`, 409);
      const t: Team = { id: id('team'), name, icon: 'team', ownerGroups: [input.ownerGroup], scope: 'owned', memberCount: 1 };
      teams.push(t);
      return t;
    }),
};
