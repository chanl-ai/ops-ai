/** A demo person as the dev sign-in route lists them: their teams, each with their role there. */
export interface DemoPersonRow {
  name: string;
  email: string;
  teams: { team: string; role: string }[];
}

/**
 * The picker's sections: one per team in the order the route first names it, each person under every team they are
 * in with their role there. A person in no team is listed under "No team".
 */
export function demoPeopleByTeam(people: DemoPersonRow[]): { team: string; people: { name: string; email: string; role: string }[] }[] {
  const groups = new Map<string, { name: string; email: string; role: string }[]>();
  for (const p of people) {
    const teams = p.teams.length ? p.teams : [{ team: 'No team', role: '' }];
    for (const t of teams) {
      const list = groups.get(t.team) ?? [];
      list.push({ name: p.name, email: p.email, role: t.role });
      groups.set(t.team, list);
    }
  }
  return [...groups].map(([team, members]) => ({ team, people: members }));
}
