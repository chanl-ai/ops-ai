import type { ConnectApproval, ConnectAudience, ConnectOverview, ConnectRange, ConnectSettings, ConnectTool } from '@/lib/types/connect';
import type { Deployment, Risk, Tool, Workflow } from '@/lib/types/domain';

import { ApiError } from '../../contract';
import type { ConnectApi } from '../../connect-contract';
import { id, notFound, respond } from '../runtime';
import { inTeam } from '../teams';
import { MCP_URL, NEW_EXPOSURE_CALLS_PER_DAY, SEED_ASSISTANTS, SEED_EXPOSED } from './seed';
import type { MockWorkflow } from '../fixtures';

export interface ConnectDeps {
  workflows: () => MockWorkflow[];
  /** The live deployments store; MCP deployments are created and paused in it. */
  deployments: Deployment[];
  tierOf: (workflowId: string) => Risk;
  /** The live tools store; exposing a workflow to agents registers a `workflow` tool in it. */
  tools: Tool[];
  teams: string[];
  me: string;
}

const DAY = 86_400_000;
const RANGE_DAYS: Record<ConnectRange, number> = { '24h': 1, '7d': 7, '30d': 30 };
const toolIdOf = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

function hash(key: string) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10_000) / 10_000;
}

/**
 * Connect over the existing stores. Which workflows are exposed is read from MCP deployments; tiers come from the
 * model inventory; approval behaviour from each workflow's review gates. Call volume and connected assistants are
 * seeded, because nothing else in the mock records MCP traffic.
 */
export function createConnectMock(deps: ConnectDeps) {
  const callsPerDay: Record<string, number> = {};
  let copied = false;
  let settings: ConnectSettings = { allowedTeams: [], defaultExposed: false, tokenLifetimeHours: 8, updatedAt: new Date(Date.now() - 12 * DAY).toISOString(), updatedBy: 'Priya Shah' };

  const mcpOf = (wid: string) => deps.deployments.find((d) => d.channel === 'mcp' && d.workflowId === wid);
  const toolOf = (wid: string) => deps.tools.find((t) => t.workflow?.workflowId === wid);
  const audiencesOf = (wid: string): ConnectAudience[] => [...(mcpOf(wid)?.status === 'active' ? (['assistants'] as const) : []), ...(toolOf(wid) ? (['agents'] as const) : [])];
  /** A workflow exposed to agents is a write tool: calling it starts a run, which keeps the workflow's own gates. */
  const workflowTool = (w: Workflow): Tool => {
    const approval = approvalOf(w);
    return {
      id: `tl_wf_${w.id.replace(/^wf_/, '')}`,
      name: toolIdOf(w.name),
      description: `Starts a run of ${w.name}. ${w.description}`,
      type: 'workflow',
      system: 'Workflows',
      module: 'Workflows',
      access: 'write',
      requiresReview: approval !== 'runs_without_pause',
      enabled: true,
      calls24h: 0,
      errorRate: 0,
      p95Ms: 0,
      grantedAgentIds: [],
      sampleInput: JSON.stringify({ subject: 'e.g. Customer disputes a $1,240.18 charge' }, null, 2),
      workflow: { workflowId: w.id, tier: deps.tierOf(w.id), approval },
    };
  };
  const newDeployment = (w: Workflow, createdAt: string): Deployment => ({
    id: id('dp'),
    name: `${w.name} · MCP`,
    workflowId: w.id,
    workflowName: w.name,
    channel: 'mcp',
    environment: 'production',
    version: w.version,
    latestVersion: w.version,
    status: 'active',
    traffic24h: 0,
    errors24h: 0,
    createdAt,
    updatedAt: createdAt,
    mcp: { toolId: toolIdOf(w.name) },
  });
  for (const s of SEED_EXPOSED) {
    const w = deps.workflows().find((x) => x.id === s.workflowId);
    if (!w) continue;
    const d = newDeployment(w, new Date(Date.now() - s.daysAgo * DAY).toISOString());
    d.traffic24h = s.callsPerDay;
    deps.deployments.push(d);
    callsPerDay[w.id] = s.callsPerDay;
  }

  const approvalOf = (w: Workflow): ConnectApproval => (w.gateCount ? (w.gateCount > 1 ? 'pauses_always' : 'pauses_on_writes') : 'runs_without_pause');
  /** Calls on one day for one workflow: zero before it was exposed or while paused, else its rate with a small daily wobble. */
  const callsOn = (wid: string, dayStart: number, d?: Deployment) => {
    if (!d || d.status !== 'active' || new Date(d.createdAt).getTime() > dayStart + DAY) return 0;
    return Math.round((callsPerDay[wid] ?? 0) * (0.75 + hash(`${wid}:${Math.floor(dayStart / DAY)}`) * 0.5));
  };

  const overview = (range: ConnectRange, empty: boolean): ConnectOverview => {
    const days = RANGE_DAYS[range];
    const wfs = empty ? [] : deps.workflows().filter((w) => inTeam(w.owner));
    const today = Math.floor(Date.now() / DAY) * DAY;
    const dayStarts = Array.from({ length: days === 1 ? 1 : days }, (_, i) => today - (days - 1 - i) * DAY);
    const tools: ConnectTool[] = wfs.map((w) => {
      const d = mcpOf(w.id);
      const calls = dayStarts.reduce((n, t) => n + callsOn(w.id, t, d), 0);
      return {
        workflowId: w.id,
        name: w.name,
        toolId: d?.mcp?.toolId ?? toolIdOf(w.name),
        tier: deps.tierOf(w.id),
        approval: approvalOf(w),
        calls,
        exposed: d?.status === 'active',
        exposedTo: audiencesOf(w.id),
        grantedAgents: toolOf(w.id)?.grantedAgentIds.length ?? 0,
        deploymentId: d?.id,
        disabledReason: w.status === 'draft' ? 'Not published yet. Publish the workflow to expose it.' : undefined,
      };
    });
    const exposed = tools.filter((t) => t.exposedTo.length > 0);
    const series = dayStarts.map((t) => {
      const calls = wfs.reduce((n, w) => n + callsOn(w.id, t, mcpOf(w.id)), 0);
      const gated = wfs.filter((w) => w.gateCount).reduce((n, w) => n + callsOn(w.id, t, mcpOf(w.id)), 0);
      return { date: new Date(t).toISOString().slice(0, 10), calls, held: Math.round(gated * 0.12), failed: Math.round(calls * 0.02) };
    });
    const assistants = empty
      ? []
      : SEED_ASSISTANTS.filter((a) => inTeam(a.team) && (!settings.allowedTeams.length || settings.allowedTeams.includes(a.team)))
          .map((a) => ({ id: a.id, client: a.client, person: a.person, team: a.team, lastCallAt: new Date(Date.now() - a.minutesAgo * 60_000).toISOString(), calls: a.calls, assurance: a.assurance }))
          .sort((x, y) => y.lastCallAt.localeCompare(x.lastCallAt));
    const total = series.reduce((n, s) => n + s.calls, 0);
    return {
      url: MCP_URL,
      authLabel: 'Workspace SSO (OAuth)',
      journey: { copiedUrl: copied || assistants.length > 0, installedClient: assistants.length > 0, firstCall: total > 0 && assistants.length > 0 },
      live: total > 0 && assistants.length > 0,
      range,
      stats: { calls: total, held: series.reduce((n, s) => n + s.held, 0), failed: series.reduce((n, s) => n + s.failed, 0), assistants: assistants.length },
      series,
      tools: [...tools].sort((x, y) => y.exposedTo.length - x.exposedTo.length || y.calls - x.calls || x.name.localeCompare(y.name)).slice(0, 5),
      workflowCount: tools.length,
      exposedCount: exposed.length,
      assistants: assistants.slice(0, 5),
      assistantCount: assistants.length,
      settings,
      teams: deps.teams,
    };
  };

  const api: ConnectApi = {
    get: (p) => respond((m) => overview(p.range, m === 'empty')),
    setExposed: (wid, audience, exposed) =>
      respond(() => {
        const w = deps.workflows().find((x) => x.id === wid) ?? notFound('Workflow');
        if (exposed && w.status === 'draft') throw new ApiError(`${w.name} has no published version. Publish it before exposing it.`, 422);
        const now = new Date().toISOString();
        if (audience === 'agents') {
          const t = toolOf(wid);
          if (exposed && !t) deps.tools.push(workflowTool(w));
          if (!exposed && t) {
            if (t.grantedAgentIds.length) throw new ApiError(`${t.grantedAgentIds.length === 1 ? 'An agent is' : `${t.grantedAgentIds.length} agents are`} granted ${t.name}. Revoke the grant on each agent first.`, 409);
            deps.tools.splice(deps.tools.indexOf(t), 1);
          }
        } else {
          let d = mcpOf(wid);
          if (exposed) {
            if (!d) {
              d = newDeployment(w, now);
              deps.deployments.unshift(d);
              callsPerDay[wid] ??= NEW_EXPOSURE_CALLS_PER_DAY;
            } else Object.assign(d, { status: 'active', updatedAt: now });
          } else if (d) Object.assign(d, { status: 'paused', updatedAt: now });
        }
        const d = mcpOf(wid);
        return overview('7d', false).tools.find((t) => t.workflowId === wid) ?? { workflowId: wid, name: w.name, toolId: toolIdOf(w.name), tier: deps.tierOf(wid), approval: approvalOf(w), calls: 0, exposed: d?.status === 'active', exposedTo: audiencesOf(wid), grantedAgents: toolOf(wid)?.grantedAgentIds.length ?? 0, deploymentId: d?.id };
      }),
    recordCopy: () =>
      respond(() => {
        copied = true;
      }),
    saveSettings: (input) =>
      respond(() => {
        if (input.tokenLifetimeHours < 1 || input.tokenLifetimeHours > 24 * 7) throw new ApiError('Token lifetime must be between 1 hour and 7 days.', 400);
        settings = { ...input, updatedAt: new Date().toISOString(), updatedBy: deps.me };
        return settings;
      }),
  };
  return { api };
}
