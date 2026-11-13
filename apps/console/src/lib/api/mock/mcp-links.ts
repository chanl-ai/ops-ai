import type { McpLink, McpLinkTool } from '@/lib/types/mcp-links';

import { ApiError } from '../contract';
import type { McpLinksApi } from '../mcp-links-contract';
import { id, notFound, respond } from './runtime';

const BASE = 'https://tools.ops.example/mcp';
const HOUR = 3_600_000;

const tool = (name: string, title: string, access: McpLinkTool['access'] = 'read'): McpLinkTool => ({ name, title, kind: access === 'workflow' ? 'workflow' : 'tool', access });

/** Sample links from several lines of work, for the all-mock console only; a real stack reads tools-service. */
function seed(now: number): McpLink[] {
  const link = (slug: string, name: string, tools: McpLinkTool[], last: McpLink['lastCall']): McpLink => ({
    id: `mcl_${slug}`,
    name,
    slug,
    teamId: 'team_ops',
    environment: 'test',
    url: `${BASE}/team_ops/${slug}`,
    tools,
    toolCount: tools.length,
    paused: false,
    createdBy: 'Priya Shah',
    createdAt: new Date(now - 72 * HOUR).toISOString(),
    lastCall: last,
  });
  return [
    link('claims-lookups', 'Claims lookups', [tool('read_claim', 'Guidewire · Read claim'), tool('find_account', 'Salesforce · Find account'), tool('update_case', 'Salesforce · Update case', 'write')], { at: new Date(now - HOUR).toISOString(), outcome: 'ok', client: 'Cursor', signedIn: false }),
    link('card-disputes-desk', 'Card disputes desk', [tool('search_disputes', 'Disputes · Search history'), tool('workflow__wf_dispute_intake', 'Dispute intake', 'workflow')], { at: new Date(now - 0.05 * HOUR).toISOString(), outcome: 'ok', client: 'Claude', signedIn: false }),
    link('outage-desk', 'Outage desk', [tool('lookup_incident', 'ServiceNow · Look up incident')], null),
  ];
}

export function createMcpLinksMock(): McpLinksApi {
  let links: McpLink[] | null = null;
  const all = () => (links ??= seed(Date.now()));
  const find = (lid: string) => all().find((l) => l.id === lid) ?? notFound(`MCP link ${lid}`);
  return {
    list: () => respond((m) => (m === 'empty' ? [] : all())),
    get: (lid) => respond(() => find(lid)),
    create: (input) =>
      respond(() => {
        const slug = input.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'link';
        if (all().some((l) => l.slug === slug)) throw new ApiError(`This team already has a link named ${input.name}.`, 422);
        const tools = input.tools.map((t) => (t.id.startsWith('workflow:') ? tool(`workflow__${t.id.slice(9)}`, t.label, 'workflow') : tool(t.id, t.label)));
        const made: McpLink = { id: id('mcl'), name: input.name, slug, teamId: 'team_ops', environment: 'test', url: `${BASE}/team_ops/${slug}`, tools, toolCount: tools.length, paused: false, createdBy: 'You', createdAt: new Date().toISOString(), lastCall: null };
        all().push(made);
        return made;
      }),
    setPaused: (lid, paused) =>
      respond(() => {
        const l = find(lid);
        l.paused = paused;
        return l;
      }),
  };
}
