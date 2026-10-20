// Writes the console mock's tool-module seed as JSON for tools-service, so the API serves the same Northfield modules
// the mock shows: the dev seed (services/tools-service/seed/, what `make up` loads) and the tests' fixture, which adds
// the mock's workflows for the tests' stand-in workflow directory. Workflows themselves are agents-service's, so the
// dev seed carries none; each seeded approval keeps its workflow's name and owning team. Run from the repo root after
// the console seed changes: `node services/tools-service/scripts/export-console-seed.mjs`.
// Times stay relative (days ago, days until expiry); the service turns them into timestamps when it seeds.
import { readFileSync, writeFileSync } from 'node:fs';

const root = new URL('../../../apps/console/src/lib/api/mock/', import.meta.url);
const s = await import(new URL('tool-modules/seed.ts', root));
const F = await import(new URL('fixtures.ts', root));
const I = await import(new URL('integrations/seed.ts', root));
// teams.ts imports extensionless paths Node cannot resolve, so its literal array is read as text.
const teamsTs = readFileSync(new URL('teams.ts', root), 'utf8');
const defaultTeam = readFileSync(new URL('../team-context.ts', root), 'utf8').match(/DEFAULT_TEAM_ID = '([^']+)'/)[1];
const teamList = new Function(`return ${teamsTs.match(/const teams: Team\[\] = (\[[\s\S]*?\n\]);/)[1].replaceAll('DEFAULT_TEAM_ID', JSON.stringify(defaultTeam))}`)();

const toolNames = new Set(s.MODULE_SEEDS.flatMap((m) => m.operations.map((o) => o.name)));
// `approvers` (2 for writes two people approve) is the registry's write approval policy; absent means one.
const tools = F.TOOLS.filter((t) => toolNames.has(t.name)).map(({ name, description, access, enabled, approvers }) => ({ name, description, access, enabled, ...(approvers ? { approvers } : {}) }));
const kindOf = Object.fromEntries(I.CATALOG.map((c) => [c.id, c.kind]));
const wanted = new Set(Object.values(I.MODULE_CONNECTION));
const connections = I.CONNECTIONS.map((c) => ({ id: c.id, name: c.name, kind: kindOf[c.catalogId], base: c.base, expiresIn: c.expiresIn ?? null, authMethod: c.authMethod, catalogId: c.catalogId, inModules: wanted.has(c.id) }));
const workflows = F.WORKFLOWS.map((w) => ({ id: w.id, name: w.name, owner: w.owner }));

const teamOfOwner = (owner) => teamList.find((t) => t.scope === 'owned' && t.ownerGroups.includes(owner))?.id ?? null;
const workflowById = Object.fromEntries(workflows.map((w) => [w.id, w]));
// The mock's traffic numbers stay in the mock: tools-service counts calls from its call log, so seeded modules start at zero.
const withoutTraffic = ({ calls24h, errorRate, p95Ms, ...rest }) => rest;
const modules = s.MODULE_SEEDS.map((m) => ({
  ...m,
  operations: m.operations.map((o) => (o.tool ? { ...o, tool: withoutTraffic(o.tool) } : o)),
  approvals: m.approvals.map((a) => ({ ...a, workflowName: workflowById[a.workflowId]?.name ?? a.workflowId, workflowTeamId: teamOfOwner(workflowById[a.workflowId]?.owner) })),
}));

const seed = {
  currentUser: F.CURRENT_USER.name,
  modules,
  tools,
  moduleConnection: I.MODULE_CONNECTION,
  connections,
  teams: teamList.map(({ id, name, ownerGroups, scope }) => ({ id, name, ownerGroups, scope })),
  discovery: s.DISCOVERY,
};
const write = (path, value) => writeFileSync(new URL(path, import.meta.url), JSON.stringify(value, null, 1) + '\n');
write('../seed/tool_modules.json', seed);
write('../tests/fixtures/tool_modules.json', { ...seed, workflows: workflows.map((w) => ({ ...w, teamId: teamOfOwner(w.owner) })) });
console.log(`seed: ${seed.modules.length} modules, ${tools.length} tools, ${connections.length} connections; fixture adds ${workflows.length} workflows`);
