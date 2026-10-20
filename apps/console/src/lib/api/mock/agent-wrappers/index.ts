import type { Agent, Deployment, Review, Risk, Workflow, WorkflowGraph } from '@/lib/types/domain';

import { templateGraph } from '../graphs';
import { id } from '../runtime';
import type { MockAgent, MockOwned } from '../fixtures';

/** The stored workflow record, before the API adds counts. */
type WorkflowRecord = Omit<Workflow, 'stepCount' | 'gateCount' | 'openReviews' | 'deploymentCount' | 'pendingPublish'> & MockOwned & { wrapsAgentId?: string };

export interface AgentWrapperDeps {
  /** Agent rows, with publishedVersion and paused. */
  agents: () => MockAgent[];
  workflows: WorkflowRecord[];
  graphs: Record<string, WorkflowGraph>;
  deployments: Deployment[];
  publishedOf: (agentId: string) => number | null;
  /** Creates the wrapper's publish request through the normal workflow path. */
  createPublishRequest: (workflowId: string, graph: WorkflowGraph, note: string, by: string) => Review;
  /** The request's gate as the approver sees it (model risk adds the pinned agents' evals). */
  gateOf: (r: Review) => Review;
  /** Applies an approved publish, as approving in Reviews would. */
  publishGraph: (workflowId: string, graph: WorkflowGraph, note: string, by: string) => void;
  tierOf: (workflowId: string) => Risk;
  /** Sets a new wrapper's inventory tier from its agent's grants. */
  seedTier: (workflowId: string, tier: Risk, reason: string) => void;
  toolAccess: (agentId: string) => 'read' | 'write' | undefined;
}

const SYSTEM = 'Platform';

/**
 * Agents deploy through an implicit one-step workflow, "Chat message → Agent → Reply", named after the agent and
 * flagged `wrapsAgentId`. The workflow stays the only engine unit, so the wrapper has versions, a gate and
 * evidence like any other. Every published agent has one, and a `chat` deployment on it is console chat:
 * active while the agent is, paused while it is paused.
 */
export function createAgentWrappers(deps: AgentWrapperDeps) {
  const wrapperOf = (agentId: string) => deps.workflows.find((w) => w.wrapsAgentId === agentId);
  const chatOf = (wid: string) => deps.deployments.find((d) => d.channel === 'chat' && d.workflowId === wid);

  const graphFor = (wid: string, a: Agent, version: number): WorkflowGraph => ({ workflowId: wid, ...templateGraph('chat', 'Chat message', { slug: a.slug, name: a.name, version }) });

  /**
   * Publishes a wrapper version through its own publish request. A low tier wrapper with no blockers approves
   * itself, which is recorded as an approval by the platform; anything else waits in Reviews like any publish.
   */
  const requestWrapperPublish = (w: WorkflowRecord, a: Agent, version: number, note: string): Review => {
    const graph = graphFor(w.id, a, version);
    const r = deps.createPublishRequest(w.id, graph, note, SYSTEM);
    const gate = deps.gateOf(r).publish?.evalGate;
    if (deps.tierOf(w.id) === 'low' && !gate?.blockers.length) {
      deps.publishGraph(w.id, graph, note, SYSTEM);
      Object.assign(r, { status: 'approved', decidedAt: new Date().toISOString(), decisionReason: 'Auto-approved: low tier wrapper, no gate blockers', assignee: SYSTEM, approvals: [SYSTEM] });
    }
    return r;
  };

  const syncChat = (agentId: string) => {
    const w = wrapperOf(agentId);
    const a = deps.agents().find((x) => x.id === agentId);
    const d = w && chatOf(w.id);
    if (!a || !w || !d) return;
    const status = a.paused ? 'paused' : 'active';
    if (d.status !== status) Object.assign(d, { status, updatedAt: new Date().toISOString() });
  };

  /** Creates the wrapper and its console chat deployment once; returns the wrapper id. */
  const ensureWrapper = (agentId: string, at = new Date().toISOString()): string | null => {
    const a = deps.agents().find((x) => x.id === agentId);
    const pub = deps.publishedOf(agentId);
    if (!a || pub === null) return null;
    let w = wrapperOf(agentId);
    if (!w) {
      w = { id: `wf_agent_${a.slug.replace(/-/g, '_')}`, name: a.name, description: `Runs ${a.name} on each chat message and replies. Created when the agent was first deployed.`, owner: a.owner, teamId: a.teamId, trigger: 'Chat message', agentSlugs: [a.slug], runs24h: 0, reviewed24h: 0, status: 'live', version: 1, updatedAt: at, wrapsAgentId: a.id };
      deps.workflows.push(w);
      deps.graphs[w.id] = graphFor(w.id, a, pub);
      const access = deps.toolAccess(a.id);
      const tier: Risk = access === 'write' ? 'medium' : 'low';
      deps.seedTier(w.id, tier, access ? `Wraps ${a.name}, whose ${access} tools set the tier` : `Wraps ${a.name}, which holds read tools only`);
    }
    if (!chatOf(w.id)) {
      deps.deployments.push({ id: id('dp'), name: `${a.name} · Console chat`, workflowId: w.id, workflowName: w.name, channel: 'chat', environment: 'production', version: w.version, latestVersion: w.version, status: a.paused ? 'paused' : 'active', traffic24h: Math.round(a.tasks24h * 0.15), errors24h: 0, createdAt: at, updatedAt: at });
    }
    return w.id;
  };

  /** Called when an agent version is published: create the wrapper, or request a wrapper publish pinned to it. */
  const onAgentPublished = (agentId: string, version: number) => {
    const existing = wrapperOf(agentId);
    const wid = ensureWrapper(agentId);
    const a = deps.agents().find((x) => x.id === agentId);
    if (!existing || !wid || !a) return;
    requestWrapperPublish(existing, a, version, `Pin ${a.name} v${version}`);
  };

  // Every agent published at seed time has its wrapper and console chat deployment.
  for (const a of deps.agents()) ensureWrapper(a.id, new Date(Date.now() - 30 * 86_400_000).toISOString());

  return {
    wrapperOf: (agentId: string) => wrapperOf(agentId)?.id,
    ensureWrapper,
    onAgentPublished,
    syncChat,
    /** The agents console chat may offer: those whose chat deployment is active. */
    chatActive: (agentId: string) => {
      const w = wrapperOf(agentId);
      return !!w && chatOf(w.id)?.status === 'active';
    },
  };
}
