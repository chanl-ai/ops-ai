import type {
  Agent,
  BulkResult,
  Deployment,
  TestCase,
  TestOutcome,
  TestResult,
  ValidationRun,
  Version,
  WorkflowRun,
  GatePolicy,
  Review,
  Tool,
  Workflow,
  WorkflowDetail,
  WorkflowGraph,
} from '@/lib/types/domain';
import type { ConnectionActivity, ConnectionRef, Dependant } from '@/lib/types/integrations';

import { ApiError, type Lookups, type OpsApi } from '../contract';
import { createCasesMock } from './cases';
import { createChatMock } from './chat';
import { createKnowledgeMock } from './knowledge';
import { createKnowledgeChangesMock } from './knowledge-changes';
import { createNotificationsMock } from './notifications';
import { runAsApi, scopeTurn } from './run-as';
import { createSearchMock } from './search';
import { createGovernanceMock } from './governance';
import { createToolModulesMock } from './tool-modules';
import { createIntegrationsMock } from './integrations';
import { MAILBOX_CONNECTION } from './integrations/seed';
import { createEvalsMock } from './evals';
import { createModelRiskMock } from './model-risk';
import { createFilesMock } from './files';
import { auditSink } from './governance';
import { bulk, field, id, list, notFound, respond } from './runtime';
import * as F from './fixtures';
import { countGates, countSteps, SEED_GRAPHS, templateGraph } from './graphs';
import { runsFor, testTurnFor, versionsFor } from './history';
import { guardTeam, inTeam, teamOwner, teamsApi } from './teams';

const isOpen = (r: Review) => r.status === 'pending' || r.status === 'in_review';

/** Version lists are returned newest first whatever order writes appended them in. */
const newestFirst = (list: Version[]) => [...list].sort((a, b) => b.version - a.version);

function pushVersion(list: Version[], version: number, note: string, changes: string[], by: string) {
  list.forEach((v) => (v.current = false));
  list.unshift({ version, publishedAt: new Date().toISOString(), publishedBy: by, note, changes, current: true });
}

/** In-memory implementation of OpsApi for demos and UI review. Transport behaviour lives in ./runtime. */
export function createMockApi(): OpsApi {
  const policies: GatePolicy[] = F.POLICIES.map((p) => ({ ...p, workflowName: '' }));
  const workflows = F.WORKFLOWS.map((w) => ({ ...w }));
  const graphs: Record<string, WorkflowGraph> = Object.fromEntries(Object.entries(SEED_GRAPHS).map(([k, g]) => [k, { workflowId: k, ...g }]));
  const agents = F.AGENTS.map((a) => ({ ...a, guardrails: { ...a.guardrails } }));
  const tools: Tool[] = F.TOOLS.map((t) => ({ ...t }));
  // Team scoping: a record is in the current team when its owner is (reviews, gates, deployments and cases
  // through their workflow; tools through the agents granted them; knowledge through sources and citing agents).
  const wfOwner = (wid: string) => workflows.find((w) => w.id === wid)?.owner;
  const teamAgents = () => agents.filter((a) => inTeam(a.owner));
  const teamWorkflows = () => workflows.filter((w) => inTeam(w.owner));
  const toolInTeam = (t: Tool) => inTeam(agents.filter((a) => t.grantedAgentIds.includes(a.id)).map((a) => a.owner));
  // Integrations own every connection; sources, modules and mailboxes hold its id and read its status through these.
  // Assigned below once the dependants' stores exist; only called at request time.
  let integrations: ReturnType<typeof createIntegrationsMock> | undefined;
  const connectionRef = (cid?: string): ConnectionRef | undefined => {
    const l = integrations?.link(cid);
    return l && { id: l.id, name: l.name, kind: l.kind, status: l.status, expiresAt: l.expiresAt };
  };
  // Every byte goes through the files store; other mocks hold file ids and record themselves as references.
  // `reviews` is read at request time, after it is built below.
  const files = createFilesMock({
    me: F.CURRENT_USER.name,
    modelEntry: (mid) => {
      const ref = mid.replace(/^mr_/, '');
      const w = workflows.find((x) => x.id === ref);
      const a = agents.find((x) => x.id === ref);
      return w ? { name: w.name, owner: w.owner, version: w.version } : a ? { name: a.name, owner: a.owner, version: a.version } : undefined;
    },
    review: (rid) => {
      const r = reviews.find((x) => x.id === rid);
      return r && { id: r.id, kind: r.kind, workflowName: r.workflowName, toVersion: r.publish?.toVersion, owner: wfOwner(r.workflowId) ?? 'Platform' };
    },
    auditCount: () => auditSink.entries().length,
  });
  const knowledge = createKnowledgeMock({
    files: () => files.links,
    connection: connectionRef,
    agentNames: (kbName) => agents.filter((a) => a.collections.includes(kbName)).map((a) => a.name),
    agentOwners: (kbName) => agents.filter((a) => a.collections.includes(kbName)).map((a) => a.owner),
    currentUser: F.CURRENT_USER.name,
  });
  const wfName = (wid: string) => workflows.find((w) => w.id === wid)?.name ?? wid;
  const cases = createCasesMock({ me: F.CURRENT_USER.name, workflowName: wfName, workflowOwner: wfOwner, files: files.links });
  const chat = createChatMock({ knowledge: knowledge.api, ground: knowledge.retrieveNow, agents: () => agents.filter((a) => a.status === 'live'), agentOwner: (aid) => agents.find((a) => a.id === aid)?.owner, reviews: () => self.reviews, me: F.CURRENT_USER.name, slaByQueue: cases.slaByQueue, files: files.links });

  const reviews: Review[] = F.REVIEWS.map((s) => {
    const p = policies.find((x) => x.id === s.policyId)!;
    return {
      id: s.id,
      title: s.title,
      customer: s.customer,
      workflowId: s.workflowId,
      workflowName: wfName(s.workflowId),
      agentSlug: s.agentSlug,
      kind: s.kind,
      risk: s.risk,
      confidence: s.confidence,
      proposal: s.proposal,
      actionTool: F.ACTION_TOOL[s.workflowId],
      amount: s.amount,
      currency: 'CAD',
      policy: { id: p.id, name: p.name, condition: p.condition, reviewers: p.reviewers, sla: p.sla, onTimeout: p.onTimeout, fourEyes: p.fourEyes },
      slaMinutes: s.slaMinutes,
      assignee: s.assignee,
      approvals: [],
      status: s.status,
      createdAt: F.reviewCreatedAt(s.createdMinutesAgo),
      decidedAt: isOpen(s as unknown as Review) ? undefined : F.reviewCreatedAt(s.createdMinutesAgo - 20),
      decisionReason: s.decisionReason,
      reasoning: s.reasoning,
      evidence: s.evidence,
    };
  });

  const withAgentName = (r: Review): Review => ({ ...r, agentName: agents.find((a) => a.slug === r.agentSlug)?.name });
  const teamReviews = () => reviews.filter((r) => inTeam(wfOwner(r.workflowId)));

  const versions: Record<string, Version[]> = {};
  /** Content of each saved version, so Restore brings back what that version actually was. */
  const agentSnapshots: Record<string, Record<number, object>> = {};
  const graphSnapshots: Record<string, Record<number, WorkflowGraph>> = {};
  const agentContent = (a: (typeof agents)[number]) => structuredClone({ name: a.name, role: a.role, model: a.model, owner: a.owner, channels: a.channels, instructions: a.instructions, toolIds: a.toolIds, collections: a.collections, guardrails: a.guardrails });
  const snapAgent = (a: (typeof agents)[number]) => ((agentSnapshots[a.id] ??= {})[a.version] = agentContent(a));
  const snapGraph = (wid: string, version: number) => graphs[wid] && ((graphSnapshots[wid] ??= {})[version] = structuredClone(graphs[wid]));
  const versionsOf = (key: string, current: number, kind: 'workflow' | 'agent') => (versions[key] ??= versionsFor(key, current, kind));
  const runCache: Record<string, WorkflowRun[]> = {};
  const runsOf = (wid: string) => {
    const w = workflows.find((x) => x.id === wid);
    return (runCache[wid] ??= runsFor(wid, graphs[wid], w?.version ?? 1, reviews.filter((r) => r.workflowId === wid && isOpen(r)).map((r) => r.id), w?.status === 'draft' ? 0 : 46));
  };

  // Seed pins: every agent step records the agent version it was published with. The wire workflow is one
  // version behind so the "republish to adopt" state is visible.
  for (const [wid, g] of Object.entries(graphs))
    for (const n of g.nodes) {
      const a = agents.find((x) => x.slug === n.data.agentSlug);
      if (a && n.data.agentVersion == null) {
        n.data.agentVersion = wid === 'wf_wire' ? a.version - 1 : a.version;
        n.data.badge = `agent · ${a.slug} · v${n.data.agentVersion}`;
      }
    }
  for (const a of agents) snapAgent(a);
  for (const w of workflows) snapGraph(w.id, w.version);
  const agentRow = (a: (typeof agents)[number]): Agent => {
    const usedIn = workflows.flatMap((w) => {
      const n = graphs[w.id]?.nodes.find((x) => x.data.agentSlug === a.slug);
      return n ? [{ workflowId: w.id, workflowName: w.name, pinnedVersion: (n.data.agentVersion as number) ?? a.version, status: w.status }] : [];
    });
    return { ...a, usedIn, workflowIds: usedIn.map((u) => u.workflowId) };
  };

  const policyRow = (p: GatePolicy): GatePolicy => ({ ...p, workflowName: wfName(p.workflowId) });
  const deployments: Deployment[] = [];
  const pendingGraphs: Record<string, WorkflowGraph> = {};
  const drafts: Record<string, NonNullable<WorkflowDetail['draft']>> = {};
  const workflowRow = (w: (typeof workflows)[number]): Workflow => {
    const g = graphs[w.id] ?? { nodes: [] };
    const pending = reviews.find((r) => r.kind === 'publish_request' && r.workflowId === w.id && isOpen(r));
    return {
      ...w,
      stepCount: countSteps(g),
      gateCount: countGates(g),
      openReviews: reviews.filter((r) => r.workflowId === w.id && isOpen(r) && r.kind !== 'publish_request').length,
      deploymentCount: deployments.filter((d) => d.workflowId === w.id).length,
      pendingPublish: pending?.publish ? { reviewId: pending.id, toVersion: pending.publish.toVersion, requestedBy: pending.publish.requestedBy } : undefined,
    };
  };

  /** Applies an approved publish: pins agent versions, records the version, and resets cached runs. */
  const publishGraph = (wid: string, graph: WorkflowGraph, note: string, by: string) => {
    const w = workflows.find((x) => x.id === wid) ?? notFound('Workflow');
    if (!graph?.nodes?.length) throw new ApiError('The graph is empty; nothing was published.', 400);
    for (const n of graph.nodes) {
      const a = agents.find((x) => x.slug === n.data.agentSlug);
      if (a) Object.assign(n.data, { agentVersion: a.version, badge: `agent · ${a.slug} · v${a.version}` });
    }
    const list = versionsOf(wid, w.version, 'workflow');
    const before = graphs[wid];
    graphs[wid] = graph;
    // The approved draft is now live; edits made after the request stay as the new draft.
    if (drafts[wid] && JSON.stringify(drafts[wid].graph) === JSON.stringify(graph)) delete drafts[wid];
    Object.assign(w, { version: w.version + 1, status: 'live', updatedAt: new Date().toISOString() });
    const added = graph.nodes.filter((n) => !before?.nodes.some((b) => b.id === n.id)).length;
    const removed = (before?.nodes ?? []).filter((b) => !graph.nodes.some((n) => n.id === b.id)).length;
    pushVersion(list, w.version, note, [note, `${added} added, ${removed} removed`], by);
    snapGraph(wid, w.version);
    delete runCache[wid];
    return w;
  };

  // ── Tests and validation: outcomes are derived from the graph, so edits change results ──
  const tests: TestCase[] = F.TEST_CASES.map((t) => ({ ...t, expect: { ...t.expect } }));
  const validations: Record<string, ValidationRun> = {};
  const outcomeOf = (g: WorkflowGraph | undefined, t: TestCase): TestOutcome => {
    const nodes = g?.nodes ?? [];
    const gate = nodes.some((n) => n.type === 'review');
    const toolsInGraph = nodes.map((n) => n.data.description).filter(Boolean);
    const agentTools = agents.filter((a) => nodes.some((n) => n.data.agentSlug === a.slug)).flatMap((a) => tools.filter((x) => a.toolIds.includes(x.id)).map((x) => x.name));
    const callable = new Set([...toolsInGraph, ...agentTools]);
    const paused = t.expect.pauses === 'yes' ? gate : t.expect.pauses === 'no' ? false : gate;
    const toolsCalled = t.expect.callsTool && callable.has(t.expect.callsTool) ? [t.expect.callsTool] : [...callable].slice(0, 1);
    const reply = t.expect.replyContains ? `…${t.expect.replyContains}…` : 'Done.';
    let failure: string | undefined;
    if (t.expect.pauses === 'yes' && !gate) failure = 'The run finished without pausing for review.';
    else if (t.expect.callsTool && !callable.has(t.expect.callsTool)) failure = `${t.expect.callsTool} was never called.`;
    else if (!nodes.length) failure = 'The workflow has no steps.';
    return { passed: !failure, paused, toolsCalled, reply, failure };
  };
  const validate = (wid: string, draft: WorkflowGraph, target: 'draft' | 'live'): ValidationRun => {
    const cases = tests.filter((t) => t.workflowId === wid);
    const live = graphs[wid];
    const results: TestResult[] = cases.map((t) => {
      const d = outcomeOf(draft, t);
      const l = target === 'draft' ? outcomeOf(live, t) : null;
      return { caseId: t.id, caseName: t.name, draft: d, live: l, regression: !!l?.passed && !d.passed };
    });
    const ctxTools = tools.map((t) => t.name);
    const checksFailing = draft.nodes.filter((n) => n.data.kind === 'agent' && !agents.some((a) => a.slug === n.data.agentSlug)).length +
      draft.nodes.filter((n) => n.data.kind === 'tool' && !ctxTools.includes(n.data.description)).length;
    const run: ValidationRun = {
      id: id('val'),
      workflowId: wid,
      ranAt: new Date().toISOString(),
      target,
      results,
      summary: { passed: results.filter((r) => r.draft.passed).length, total: results.length, regressions: results.filter((r) => r.regression).length, checksFailing },
    };
    validations[wid] = run;
    return run;
  };
  const PUBLISH_POLICY = { id: 'gp_publish', name: 'Publish approval', condition: 'every publish', reviewers: 'Workflow publishers', sla: '1 business day', onTimeout: 'Request expires', fourEyes: false };
  const createPublishRequest = (wid: string, graph: WorkflowGraph, note: string, by: string, validation: ValidationRun | null): Review => {
    const w = workflows.find((x) => x.id === wid) ?? notFound('Workflow');
    const before = graphs[wid];
    const added = graph.nodes.filter((n) => !before?.nodes.some((b) => b.id === n.id)).map((n) => `Added ${n.data.label}`);
    const removed = (before?.nodes ?? []).filter((b) => !graph.nodes.some((n) => n.id === b.id)).map((n) => `Removed ${n.data.label}`);
    const changed = graph.nodes.filter((n) => {
      const b = before?.nodes.find((x) => x.id === n.id);
      return b && JSON.stringify({ ...b.data, status: undefined }) !== JSON.stringify({ ...n.data, status: undefined });
    }).map((n) => `Changed ${n.data.label}`);
    const changes = [...added, ...changed, ...removed];
    const v = validation?.summary ?? null;
    const r: Review = {
      id: `PUB-${String(1000 + reviews.filter((x) => x.kind === 'publish_request').length + 1)}`,
      title: `Publish ${w.name} v${w.version + 1}`,
      customer: `Requested by ${by}`,
      workflowId: wid,
      workflowName: w.name,
      agentSlug: by,
      kind: 'publish_request',
      risk: v?.regressions ? 'high' : v && v.passed < v.total ? 'medium' : 'low',
      confidence: v?.total ? v.passed / v.total : 1,
      proposal: note,
      actionTool: 'publish_workflow',
      currency: 'CAD',
      policy: PUBLISH_POLICY,
      slaMinutes: 480,
      approvals: [],
      status: 'pending',
      createdAt: new Date().toISOString(),
      reasoning: changes.length ? changes : ['Only positions changed'],
      evidence: v ? [{ kind: 'tool', label: 'Validation', detail: `${v.passed}/${v.total} tests passed · ${v.regressions} regressions` }] : [],
      publish: { workflowId: wid, fromVersion: w.version, toVersion: w.version + 1, note, requestedBy: by, changes, validation: v },
    };
    reviews.unshift(r);
    pendingGraphs[r.id] = graph;
    return r;
  };
  const agentOr404 = (aid: string) => agents.find((a) => a.id === aid) ?? notFound('Agent');
  const agentById = (aid: string) => agentRow(agentOr404(aid));
  const me = F.CURRENT_USER.name;

  const lookups = (): Lookups => ({
    owners: F.OWNERS,
    models: F.MODELS,
    reviewerGroups: [...new Set([...F.REVIEWER_GROUPS, ...policies.map((p) => p.reviewers)])].sort(),
    reviewers: F.REVIEWERS,
    slaOptions: F.SLA_OPTIONS,
    collections: knowledge.kbNames(),
    systems: F.SYSTEMS,
    workflows: teamWorkflows().map((w) => ({ id: w.id, name: w.name })),
    currentUser: F.CURRENT_USER,
    workspace: F.WORKSPACE,
  });

  const deploymentRow = (d: Deployment): Deployment => {
    const w = workflows.find((x) => x.id === d.workflowId);
    // A mailbox's first sync finishes a few seconds after connecting, so the sheet shows it moving to healthy.
    if (d.email?.sync?.status === 'syncing' && Date.now() - new Date(d.updatedAt).getTime() > 4000)
      d.email.sync = { status: 'healthy', lastMessageAt: d.email.sync.lastMessageAt ?? new Date().toISOString(), messages24h: d.email.sync.messages24h };
    const link = d.email?.connectionId ? connectionRef(d.email.connectionId) : undefined;
    let email = d.email;
    if (email && link) {
      // Mail sync follows the mailbox's connection: a revoked, expired or failing connection stops reading mail.
      const broken = link.status === 'revoked' || link.status === 'needs_reconnect' || link.status === 'error';
      const sync: NonNullable<typeof email.sync> = broken
        ? { status: 'error', lastMessageAt: email.sync?.lastMessageAt ?? null, messages24h: email.sync?.messages24h ?? 0, error: link.status === 'revoked' ? 'The Microsoft 365 connection was revoked. New email is not being read.' : link.status === 'error' ? 'Microsoft Graph is refusing the connection. New email is not being read.' : 'Microsoft Graph returned 401: the mailbox consent expired. New email is not being read.' }
        : email.sync?.status === 'error'
          ? { status: 'syncing', lastMessageAt: email.sync.lastMessageAt, messages24h: email.sync.messages24h }
          : (email.sync ?? { status: 'healthy', lastMessageAt: null, messages24h: 0 });
      if (sync.status === 'syncing' && email.sync?.status === 'error') d.updatedAt = new Date().toISOString();
      if (d.email) d.email.sync = sync;
      email = { ...email, sync, connection: link };
    }
    return {
      ...d,
      email,
      workflowName: w?.name ?? d.workflowId,
      latestVersion: w?.version ?? d.version,
      api: d.api && { ...d.api, endpoint: `https://api.northfieldbank.com/ops/v1/run/${w ? w.id.replace('wf_', '') : d.workflowId}` },
    };
  };
  deployments.push(...F.DEPLOYMENTS.map((d) => ({ ...d, workflowName: '', latestVersion: d.version, api: d.api && { ...d.api, endpoint: '' }, email: d.email && { ...d.email, connectionId: MAILBOX_CONNECTION[d.id] } })));

  const toolModules = createToolModulesMock({ tools, agents, connection: (cid) => integrations?.link(cid) });
  const SOURCE_STATUS = { active: ['Syncing on schedule', 'ok'], paused: ['Schedule paused', 'muted'], draft: ['Draft', 'muted'], revoked: ['Stopped: connection revoked', 'bad'] } as const;
  const dependants = (cid: string): Dependant[] => [
    ...knowledge.sourcesUsing(cid).map((src): Dependant => ({
      type: 'source',
      id: src.id,
      name: src.name,
      href: `/sources/${src.id}`,
      owner: src.owner,
      status: SOURCE_STATUS[src.status][0],
      tone: src.status === 'active' && src.lastRunStatus === 'failed' ? 'bad' : SOURCE_STATUS[src.status][1],
      stops: src.status === 'revoked' ? 'Already stopped syncing' : 'Syncs stop; indexed items stay searchable but stop updating',
    })),
    ...toolModules.using(cid).map((m): Dependant => ({
      type: 'tool_module',
      id: m.id,
      name: m.displayName,
      href: `/tools/${m.id}`,
      owner: m.ownerTeam,
      status: !m.reachable ? 'Unreachable' : m.status === 'published' ? `v${m.version} · ${m.operationCount} operations` : m.status === 'draft' ? 'Draft' : 'In security review',
      tone: !m.reachable ? 'bad' : m.status === 'published' ? 'ok' : 'muted',
      stops: m.workflows.length ? `Calls fail into the human step for ${m.workflows.map((x) => x.name).join(', ')}` : 'Calls fail; no workflow holds an approval yet',
    })),
    ...deployments
      .filter((d) => d.email?.connectionId === cid)
      .map((d): Dependant => {
        const r = deploymentRow(d);
        const sync = r.email?.sync;
        return {
          type: 'mailbox',
          id: d.id,
          name: `${d.name} · ${d.email!.inboundAddress}`,
          href: `/deployments?deployment=${d.id}`,
          owner: wfOwner(d.workflowId) ?? '',
          status: sync?.status === 'error' ? 'Not reading mail' : sync?.status === 'syncing' ? 'Catching up' : 'Reading mail',
          tone: sync?.status === 'error' ? 'bad' : 'ok',
          stops: 'New email is not read and no cases open; replies cannot be sent',
        };
      }),
  ];
  const activity = (cid: string): ConnectionActivity[] =>
    [
      ...knowledge.sourcesUsing(cid).flatMap((src): ConnectionActivity[] =>
        src.lastSyncAt ? [{ id: `${src.id}_last`, at: src.lastSyncAt, kind: 'sync', label: `Sync · ${src.name}`, detail: src.lastRunStatus === 'failed' ? 'Failed' : src.lastRunStatus === 'partial' ? 'Finished with failed items' : 'Finished', ok: src.lastRunStatus !== 'failed', href: `/sources/${src.id}?tab=history` }] : [],
      ),
      ...toolModules.using(cid).flatMap((m) =>
        toolModules.recentCalls(m.id, 5).map((c): ConnectionActivity => ({ id: c.id, at: c.at, kind: 'call', label: c.target, detail: `${c.workflowName} · ${c.status === 'ok' ? 'OK' : c.status === 'awaiting_approval' ? 'Waiting for approval' : c.status === 'denied' ? 'Denied' : 'Failed'} · ${c.latencyMs} ms`, ok: c.status === 'ok' || c.status === 'awaiting_approval', href: `/logs/tool-calls?q=${encodeURIComponent(c.target)}` })),
      ),
      ...deployments
        .filter((d) => d.email?.connectionId === cid && d.email.sync?.lastMessageAt)
        .map((d): ConnectionActivity => ({ id: `${d.id}_mail`, at: d.email!.sync!.lastMessageAt!, kind: 'sync', label: `Mail · ${d.email!.inboundAddress}`, detail: d.email!.sync!.status === 'error' ? 'Last email read before the connection failed' : `${d.email!.sync!.messages24h} emails in 24 h`, ok: d.email!.sync!.status !== 'error', href: `/deployments?deployment=${d.id}` })),
    ]
      .sort((a, b) => b.at.localeCompare(a.at))
      .slice(0, 15);
  integrations = createIntegrationsMock({ me: F.CURRENT_USER.name, dependants, activity, onStatus: knowledge.reflectConnection });
  const integrationsApi = integrations.api;

  // A publish request someone else raised, so maker-checker approval can be shown end to end.
  {
    const g = structuredClone(graphs.wf_dispute);
    const gate = g.nodes.find((n) => n.type === 'review');
    if (gate) gate.data.condition = 'credit.amount > 1,500';
    const val = validate('wf_dispute', g, 'draft');
    const r = createPublishRequest('wf_dispute', g, 'Raise the review threshold for provisional credit to $1,500', 'Maya Okafor', val);
    r.createdAt = F.reviewCreatedAt(95);
    r.slaMinutes = 385;
  }

  const evals = createEvalsMock({ agents: () => agents.map(agentRow), toolName: (tid) => tools.find((t) => t.id === tid)?.name, toolAccess: (n) => tools.find((t) => t.name === n)?.access, collections: () => knowledge.kbNames(), me, files: files.links });
  const modelRisk = createModelRiskMock({ agents: () => agents.map(agentRow), workflows: () => workflows.map(workflowRow), graph: (wid) => graphs[wid], lastValidation: (wid) => validations[wid], reviews: () => reviews, toolSystem: (tid) => tools.find((t) => t.id === tid)?.system, owners: F.OWNERS, me, evals });

  const self: OpsApi = {
    overview: {
      get: () =>
        respond((m) => {
          const empty = m === 'empty';
          const open = empty ? [] : teamReviews().filter(isOpen).sort((a, b) => a.slaMinutes - b.slaMinutes);
          const live = teamAgents().filter((a) => a.status === 'live');
          const wfs = teamWorkflows();
          const tasks = live.reduce((s, a) => s + a.tasks24h, 0);
          const auto = live.reduce((s, a) => s + a.tasks24h * a.autoResolvedRate, 0);
          return {
            openReviews: open.length,
            overdueReviews: open.filter((r) => r.slaMinutes < 0).length,
            tasks24h: empty ? 0 : tasks,
            tasksTrendPct: 18,
            autoResolvedRate: empty || !tasks ? 0 : auto / tasks,
            liveAgents: empty ? 0 : live.length,
            liveWorkflows: empty ? 0 : wfs.filter((w) => w.status === 'live').length,
            draftWorkflows: empty ? 0 : wfs.filter((w) => w.status === 'draft').length,
            throughput7d: empty ? [] : F.THROUGHPUT_7D,
            urgentReviews: open.slice(0, 6),
            workflowHealth: empty ? [] : wfs.filter((w) => w.status === 'live').map(workflowRow),
            cases: empty ? { open: 0, breaching: 0, awaitingApproval: 0 } : cases.stats(),
          };
        }),
    },

    lookups: { get: () => respond(lookups) },
    teams: teamsApi,

    deployments: {
      list: (p) => respond((m) => list(deployments.filter((d) => inTeam(wfOwner(d.workflowId))).map(deploymentRow), p, { text: (d) => `${d.name} ${d.workflowName}`, value: field, facetKeys: ['channel', 'environment', 'workflowId', 'status'] }, m)),
      create: (input) =>
        respond(() => {
          const w = workflows.find((x) => x.id === input.workflowId) ?? notFound('Workflow');
          if (w.status === 'draft') throw new ApiError('Publish the workflow before deploying it. Deployments only serve published versions.', 422);
          if (input.channel === 'email' && deployments.some((d) => d.email?.inboundAddress === input.email?.inboundAddress))
            throw new ApiError(`${input.email?.inboundAddress} is already routed to another deployment.`, 409);
          // The mailbox's consent becomes a Microsoft 365 connection in Integrations that this deployment reads through.
          const email = input.email && { ...input.email, connectionId: integrations?.addMailbox(input.email.inboundAddress, w.owner), sync: { status: 'syncing' as const, lastMessageAt: null, messages24h: 0 } };
          const d: Deployment = { id: id('dp'), ...input, email, workflowName: w.name, version: w.version, latestVersion: w.version, status: 'active', traffic24h: 0, errors24h: 0, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), api: input.api && { ...input.api, keyPrefix: `nfb_${input.environment === 'production' ? 'live' : 'test'}_${Math.random().toString(36).slice(2, 5)}`, endpoint: '' } };
          deployments.unshift(d);
          return deploymentRow(d);
        }),
      update: (did, patch) =>
        respond(() => {
          const d = deployments.find((x) => x.id === did) ?? notFound('Deployment');
          const w = workflows.find((x) => x.id === d.workflowId);
          if (patch.version && w && patch.version > w.version) throw new ApiError(`v${patch.version} is not published yet.`, 422);
          Object.assign(d, patch, { updatedAt: new Date().toISOString() });
          return deploymentRow(d);
        }),
      remove: (did) =>
        respond(() => {
          const i = deployments.findIndex((x) => x.id === did);
          if (i < 0) notFound('Deployment');
          deployments.splice(i, 1);
        }),
      promote: (did, input) =>
        respond(() => {
          const d = deployments.find((x) => x.id === did) ?? notFound('Deployment');
          if (d.environment !== 'staging') throw new ApiError('Only staging deployments can be promoted.', 400);
          const copy: Deployment = {
            ...structuredClone(d),
            id: id('dp'),
            name: input.name,
            environment: 'production',
            traffic24h: 0,
            errors24h: 0,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            widget: d.widget && { ...d.widget, allowedDomains: input.allowedDomains ?? d.widget.allowedDomains },
          };
          deployments.unshift(copy);
          return deploymentRow(copy);
        }),
      rotateKey: (did) =>
        respond(() => {
          const d = deployments.find((x) => x.id === did) ?? notFound('Deployment');
          if (d.channel !== 'api' || !d.api) throw new ApiError('Only API deployments have keys.', 400);
          const env = d.environment === 'production' ? 'live' : 'test';
          const key = `nfb_${env}_${Math.random().toString(36).slice(2, 10)}${Math.random().toString(36).slice(2, 10)}`;
          d.api.keyPrefix = key.slice(0, 12);
          d.updatedAt = new Date().toISOString();
          return { key, deployment: deploymentRow(d) };
        }),
      bulkUpdate: (ids, patch) =>
        respond(() =>
          bulk(ids, (did) => {
            const d = deployments.find((x) => x.id === did);
            if (!d) return 'Not found';
            const w = workflows.find((x) => x.id === d.workflowId);
            if (patch.toLatest) {
              if (!w || d.version === w.version) return `Already on v${d.version}`;
              d.version = w.version;
            }
            if (patch.status) {
              if (d.status === patch.status) return `Already ${patch.status}`;
              d.status = patch.status;
            }
            d.updatedAt = new Date().toISOString();
          }),
        ),
      bulkRemove: (ids) =>
        respond(() =>
          bulk(ids, (did) => {
            const i = deployments.findIndex((x) => x.id === did);
            if (i < 0) return 'Not found';
            if (deployments[i].status === 'active' && deployments[i].environment === 'production') return 'Pause a production deployment before deleting it';
            deployments.splice(i, 1);
          }),
        ),
    },

    tests: {
      list: (wid) => respond((m) => (m === 'empty' ? [] : tests.filter((t) => t.workflowId === wid))),
      create: (wid, input) =>
        respond(() => {
          const t: TestCase = { id: id('tc'), workflowId: wid, ...input, source: 'manual', createdAt: new Date().toISOString() };
          tests.unshift(t);
          return t;
        }),
      importRows: (wid, rows, fileId) =>
        respond(() => {
          if (fileId) files.links.link(fileId, { type: 'test_set', id: wid, name: `${wfName(wid)} tests`, href: `/workflows/${wid}?tab=tests` }, ['test_import']);
          return bulk(
            rows.map((_, i) => String(i)),
            (i) => {
              const r = rows[Number(i)];
              if (!r.name?.trim() || !r.input?.trim()) return 'Name and input are required';
              tests.unshift({ id: id('tc'), workflowId: wid, ...r, source: 'csv', createdAt: new Date().toISOString() });
            },
          );
        }),
      fromRun: (runId) =>
        respond(() => {
          const run = Object.values(runCache).flat().find((r) => r.id === runId) ?? notFound('Run');
          const t: TestCase = {
            id: id('tc'),
            workflowId: run.workflowId,
            name: `From ${run.id} · ${run.subject}`,
            input: JSON.stringify({ subject: run.subject }),
            expect: { pauses: run.status === 'waiting_review' || run.steps.some((s) => s.kind === 'review') ? 'yes' : 'no' },
            source: 'run',
            createdAt: new Date().toISOString(),
          };
          tests.unshift(t);
          return t;
        }),
      remove: (tid) =>
        respond(() => {
          const i = tests.findIndex((x) => x.id === tid);
          if (i < 0) notFound('Test');
          const [t] = tests.splice(i, 1);
          const v = validations[t.workflowId];
          if (v) {
            v.results = v.results.filter((r) => r.caseId !== tid);
            v.summary = { ...v.summary, total: v.results.length, passed: v.results.filter((r) => r.draft.passed).length, regressions: v.results.filter((r) => r.regression).length };
          }
        }),
    },

    agents: {
      list: (p) => respond((m) => list(teamAgents().map(agentRow), p, { text: (a) => `${a.name} ${a.role} ${a.slug}`, value: field, facetKeys: ['status', 'owner'] }, m)),
      get: (aid) => respond((m) => (m === 'empty' ? notFound('Agent') : (guardTeam(agentOr404(aid).owner, 'agent'), agentById(aid)))),
      create: (input) =>
        respond(() => {
          const slug = input.name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
          if (agents.some((a) => a.slug === slug)) throw new ApiError(`An agent with the handle ${slug} already exists.`, 409);
          const a = { id: id('ag'), slug, instructions: '', ...input, toolIds: [], collections: [], status: 'draft' as const, version: 1, updatedAt: new Date().toISOString(), tasks24h: 0, autoResolvedRate: 0, workflowIds: [], guardrails: { redactPii: true, maxToolCallsPerTurn: 6, whenUnsure: 'handoff' as const, blockedTopics: [] } };
          agents.unshift(a);
          versions[a.id] = [{ version: 1, publishedAt: new Date().toISOString(), publishedBy: me, note: 'Created', changes: ['Created'], current: true }];
          snapAgent(a);
          return agentRow(a);
        }),
      update: (aid, patch) =>
        respond(() => {
          const a = agentOr404(aid);
          const { note, ...fields } = patch;
          if (fields.toolIds) for (const t of tools) t.grantedAgentIds = fields.toolIds.includes(t.id) ? [...new Set([...t.grantedAgentIds, aid])] : t.grantedAgentIds.filter((x) => x !== aid);
          const list = versionsOf(aid, a.version, 'agent');
          Object.assign(a, fields, { version: a.version + 1, updatedAt: new Date().toISOString() });
          const changed = Object.keys(fields).map((k) => ({ toolIds: 'tools', collections: 'knowledge', guardrails: 'guardrails', instructions: 'instructions', role: 'job' })[k] ?? k);
          pushVersion(list, a.version, note || `Changed ${changed.join(', ')}`, [note || `Changed ${changed.join(', ')}`], me);
          snapAgent(a);
          return agentRow(a);
        }),
      remove: (aid) =>
        respond(() => {
          const live = agentRow(agentOr404(aid)).usedIn.filter((u) => u.status === 'live');
          if (live.length) throw new ApiError(`Used by ${live.map((u) => u.workflowName).join(', ')}, which is live. Remove it from the workflow first.`, 409);
          agents.splice(agents.findIndex((a) => a.id === aid), 1);
          for (const t of tools) t.grantedAgentIds = t.grantedAgentIds.filter((x) => x !== aid);
        }),
      versions: (aid) => respond(() => newestFirst(versionsOf(aid, agentOr404(aid).version, 'agent'))),
      restore: (aid, version) =>
        respond(() => {
          const a = agentOr404(aid);
          const list = versionsOf(aid, a.version, 'agent');
          if (!list.some((v) => v.version === version)) notFound('Version');
          // Older seeded versions predate snapshots; they restore the earliest content recorded.
          const snaps = agentSnapshots[aid] ?? {};
          const snap = snaps[version] ?? snaps[Math.min(...Object.keys(snaps).map(Number))];
          if (snap) Object.assign(a, structuredClone(snap));
          a.version += 1;
          a.updatedAt = new Date().toISOString();
          pushVersion(list, a.version, `Restored v${version}`, [`Restored the configuration from v${version}`], me);
          snapAgent(a);
          return agentRow(a);
        }),
      setStatus: (aid, status) =>
        respond(() => {
          const a = agentOr404(aid);
          if (status === 'live' && !a.toolIds.length && !a.collections.length) throw new ApiError('Grant at least one tool or knowledge collection before publishing.', 422);
          a.status = status;
          a.updatedAt = new Date().toISOString();
          return agentRow(a);
        }),
      test: (aid, message, runAsId) =>
        respond(() => {
          const a = agentOr404(aid);
          return scopeTurn(testTurnFor(a, message, tools.filter((t) => a.toolIds.includes(t.id)).map((t) => t.name)), message, runAsId);
        }),
      bulkUpdate: (ids, patch) =>
        respond(() =>
          bulk(ids, (aid) => {
            const a = agents.find((x) => x.id === aid);
            if (!a) return 'Not found';
            if (patch.status && a.status === 'draft') return 'Not in use yet';
            if (patch.status && a.status === patch.status) return `Already ${patch.status}`;
            Object.assign(a, patch, { updatedAt: new Date().toISOString() });
          }),
        ),
      bulkRemove: (ids) =>
        respond(() =>
          bulk(ids, (aid) => {
            const i = agents.findIndex((x) => x.id === aid);
            if (i < 0) return 'Not found';
            if (agentRow(agents[i]).usedIn.some((u) => u.status === 'live')) return 'Used in a live workflow';
            agents.splice(i, 1);
            for (const t of tools) t.grantedAgentIds = t.grantedAgentIds.filter((x) => x !== aid);
          }),
        ),
    },

    workflows: {
      list: (p) => respond((m) => list(teamWorkflows().map(workflowRow), p, { text: (w) => `${w.name} ${w.trigger}`, value: field, facetKeys: ['status'] }, m)),
      get: (wid) =>
        respond((m): WorkflowDetail => {
          const w = m === 'empty' ? undefined : workflows.find((x) => x.id === wid);
          if (!w) return notFound('Workflow');
          guardTeam(w.owner, 'workflow');
          return { ...workflowRow(w), graph: graphs[wid], draft: drafts[wid] };
        }),
      create: (input) =>
        respond(() => {
          const w = { id: id('wf'), name: input.name, description: '', owner: teamOwner() ?? F.OWNERS[0], trigger: input.trigger, agentSlugs: [] as string[], runs24h: 0, reviewed24h: 0, status: 'draft' as const, version: 1, updatedAt: new Date().toISOString() };
          workflows.unshift(w);
          const ag = agents.find((x) => x.slug === input.agentSlug);
          graphs[w.id] = { workflowId: w.id, ...templateGraph(input.template, input.trigger, ag && { slug: ag.slug, name: ag.name, version: ag.version }) };
          if (ag) w.agentSlugs = [ag.slug];
          return workflowRow(w);
        }),
      validate: (wid, graph, target = 'draft') =>
        respond(() => {
          if (!workflows.some((x) => x.id === wid)) notFound('Workflow');
          return validate(wid, graph, target);
        }),
      lastValidation: (wid) => respond(() => validations[wid] ?? null),
      saveDraft: (wid, graph) =>
        respond(() => {
          if (!workflows.some((x) => x.id === wid)) notFound('Workflow');
          if (!graph) {
            delete drafts[wid];
            return null;
          }
          drafts[wid] = { graph: structuredClone(graph), savedAt: new Date().toISOString(), savedBy: me };
          return drafts[wid];
        }),
      requestPublish: (wid, input) =>
        respond(() => {
          if (reviews.some((r) => r.kind === 'publish_request' && r.workflowId === wid && isOpen(r)))
            throw new ApiError('A publish request for this workflow is already waiting. Decide or return it first.', 409);
          if (!input.graph?.nodes?.length) throw new ApiError('The graph is empty; there is nothing to publish.', 400);
          const v = input.validationRunId && validations[wid]?.id === input.validationRunId ? validations[wid] : null;
          if (v) v.summary.checksFailing = input.checksFailing;
          drafts[wid] = { graph: structuredClone(input.graph), savedAt: new Date().toISOString(), savedBy: me };
          return createPublishRequest(wid, input.graph, input.note, me, v);
        }),
      update: (wid, input) =>
        respond(() => {
          const w = workflows.find((x) => x.id === wid) ?? notFound('Workflow');
          Object.assign(w, input, { updatedAt: new Date().toISOString() });
          for (const r of reviews) if (r.workflowId === wid) r.workflowName = w.name;
          return workflowRow(w);
        }),
      setStatus: (wid, status) =>
        respond(() => {
          const w = workflows.find((x) => x.id === wid) ?? notFound('Workflow');
          if (status === 'live' && w.status === 'draft') throw new ApiError('Publish the draft to make it live.', 422);
          w.status = status;
          return workflowRow(w);
        }),
      remove: (wid) =>
        respond(() => {
          const i = workflows.findIndex((x) => x.id === wid);
          if (i < 0) notFound('Workflow');
          if (reviews.some((r) => r.workflowId === wid && isOpen(r))) throw new ApiError('This workflow has open reviews. Decide them or pause the workflow first.', 409);
          workflows.splice(i, 1);
        }),
      runs: (wid, p) =>
        respond((m) => {
          if (!workflows.some((x) => x.id === wid)) notFound('Workflow');
          return list(runsOf(wid), p, { text: (r) => `${r.id} ${r.subject}`, value: field, facetKeys: ['status'] }, m);
        }),
      versions: (wid) =>
        respond(() => {
          const w = workflows.find((x) => x.id === wid) ?? notFound('Workflow');
          return newestFirst(versionsOf(wid, w.version, 'workflow'));
        }),
      restore: (wid, version) =>
        respond(() => {
          const w = workflows.find((x) => x.id === wid) ?? notFound('Workflow');
          const list = versionsOf(wid, w.version, 'workflow');
          if (!list.some((v) => v.version === version)) notFound('Version');
          const snaps = graphSnapshots[wid] ?? {};
          const snap = snaps[version] ?? snaps[Math.min(...Object.keys(snaps).map(Number))];
          if (snap) graphs[wid] = structuredClone(snap);
          w.version += 1;
          w.updatedAt = new Date().toISOString();
          pushVersion(list, w.version, `Restored v${version}`, [`Restored the graph from v${version}`], me);
          snapGraph(wid, w.version);
          delete runCache[wid];
          return workflowRow(w);
        }),
      bulkUpdate: (ids, patch) =>
        respond(() =>
          bulk(ids, (wid) => {
            const w = workflows.find((x) => x.id === wid);
            if (!w) return 'Not found';
            if (patch.status && w.status === 'draft') return 'Never published';
            if (patch.status && w.status === patch.status) return `Already ${patch.status}`;
            Object.assign(w, patch);
          }),
        ),
    },

    reviews: {
      list: (p) =>
        respond((m) => {
          const scoped = teamReviews();
          const byView = scoped.filter((r) =>
            p.view === 'all' ? true : p.view === 'resolved' ? !isOpen(r) : p.view === 'overdue' ? isOpen(r) && r.slaMinutes < 0 : p.view === 'mine' ? isOpen(r) && r.assignee === me : isOpen(r),
          );
          const sorted = p.view === 'resolved' || p.view === 'all' ? byView.sort((a, b) => (b.decidedAt ?? '').localeCompare(a.decidedAt ?? '')) : byView.sort((a, b) => a.slaMinutes - b.slaMinutes);
          const result = list(sorted, p, { text: (r) => `${r.title} ${r.customer} ${r.id}`, value: field, facetKeys: ['risk', 'workflowId', 'kind'] }, m);
          result.data = result.data.map(withAgentName);
          const src = m === 'empty' ? [] : scoped;
          const open = src.filter(isOpen);
          const resolved = src.filter((r) => !isOpen(r));
          return {
            ...result,
            viewCounts: { mine: open.filter((r) => r.assignee === me).length, open: open.length, overdue: open.filter((r) => r.slaMinutes < 0).length, resolved: resolved.length },
            stats: {
              unassigned: open.filter((r) => !r.assignee).length,
              medianDecisionMinutes: resolved.length ? 11 : 0,
              medianDecisionTrendMinutes: resolved.length ? -3 : 0,
              approvedAsProposedRate: resolved.length ? resolved.filter((r) => r.status === 'approved').length / resolved.length : 0,
              decidedToday: resolved.length,
            },
          };
        }),
      get: (rid) => respond(() => withAgentName(reviews.find((x) => x.id === rid) ?? notFound('Review'))),
      decide: (rid, input) =>
        respond(() => {
          const r = reviews.find((x) => x.id === rid) ?? notFound('Review');
          if (!isOpen(r)) throw new ApiError(`${rid} was already decided.`, 409);
          if (input.decision !== 'approved' && !input.reason?.trim()) throw new ApiError('A reason is required to reject or return.', 400);
          if (input.decision === 'approved' && r.approvals.includes(me)) throw new ApiError('You already approved this. A second reviewer must approve it.', 409);
          if (r.kind === 'publish_request' && r.publish) {
            if (input.decision === 'approved') {
              if (r.publish.requestedBy === me) throw new ApiError('You requested this publish. Another publisher must approve it.', 409);
              const w = publishGraph(r.workflowId, pendingGraphs[r.id], r.publish.note, me);
              r.publish.toVersion = w.version;
            }
            delete pendingGraphs[r.id];
            Object.assign(r, { status: input.decision, decidedAt: new Date().toISOString(), decisionReason: input.reason, assignee: me, approvals: input.decision === 'approved' ? [me] : [] });
            return r;
          }
          if (input.decision === 'approved' && r.policy.fourEyes && !r.approvals.length) {
            Object.assign(r, { approvals: [me], assignee: me, status: 'in_review' });
            return r;
          }
          Object.assign(r, { status: input.decision, decidedAt: new Date().toISOString(), decisionReason: input.reason, assignee: r.assignee ?? me, approvals: input.decision === 'approved' ? [...r.approvals, me] : r.approvals });
          return r;
        }),
      assign: (ids, assignee = me) =>
        respond(() =>
          bulk(ids, (rid) => {
            const r = reviews.find((x) => x.id === rid);
            if (!r) return 'Not found';
            if (!isOpen(r)) return 'Already decided';
            Object.assign(r, { assignee, status: 'in_review' });
          }),
        ),
      bulkDecide: (ids, decision, reason) =>
        respond(() => {
          if (decision !== 'approved' && !reason?.trim()) throw new ApiError('A reason is required to reject or return.', 400);
          return bulk(ids, (rid) => {
            const r = reviews.find((x) => x.id === rid);
            if (!r) return 'Not found';
            if (!isOpen(r)) return 'Already decided';
            if (r.kind === 'publish_request') return 'Publish requests need an individual decision';
            if (decision === 'approved' && (r.risk === 'critical' || r.risk === 'high')) return `${r.risk} risk needs an individual decision`;
            if (decision === 'approved' && r.policy.fourEyes) return 'Needs two approvers';
            Object.assign(r, { status: decision, decidedAt: new Date().toISOString(), decisionReason: reason, assignee: r.assignee ?? me });
          });
        }),
    },

    policies: {
      list: (p) => respond((m) => list(policies.filter((x) => inTeam(wfOwner(x.workflowId))).map(policyRow), p, { text: (x) => `${x.name} ${x.condition} ${x.reviewers}`, value: field, facetKeys: ['workflowId'] }, m)),
      create: (input) =>
        respond(() => {
          const p: GatePolicy = { id: id('gp'), ...input, workflowName: '', hits7d: 0 };
          policies.unshift(p);
          return policyRow(p);
        }),
      update: (pid, input) =>
        respond(() => {
          const p = policies.find((x) => x.id === pid) ?? notFound('Gate');
          Object.assign(p, input);
          return policyRow(p);
        }),
      remove: (pid) =>
        respond(() => {
          const i = policies.findIndex((x) => x.id === pid);
          if (i < 0) notFound('Gate');
          policies.splice(i, 1);
        }),
      bulkUpdate: (ids, patch) =>
        respond(() =>
          bulk(ids, (pid) => {
            const p = policies.find((x) => x.id === pid);
            if (!p) return 'Not found';
            Object.assign(p, Object.fromEntries(Object.entries(patch).filter(([, v]) => v)));
          }),
        ),
      bulkRemove: (ids) =>
        respond(() =>
          bulk(ids, (pid) => {
            const i = policies.findIndex((x) => x.id === pid);
            if (i < 0) return 'Not found';
            policies.splice(i, 1);
          }),
        ),
    },

    knowledge: knowledge.api,
    knowledgeChanges: createKnowledgeChangesMock({ me, workflowName: wfName, workflowOwner: wfOwner }),
    search: createSearchMock({ workflows: teamWorkflows, agents: teamAgents, cases: cases.api, knowledge: knowledge.api, chat }),
    notifications: createNotificationsMock({ me, reviews: () => reviews }),
    runAs: runAsApi,
    cases: cases.api,
    chat,
    evals: evals.api,
    modelRisk: modelRisk.api,
    ...createGovernanceMock(),
    toolModules: toolModules.api,
    integrations: integrationsApi,
    files: files.api,

    tools: {
      list: (p) =>
        respond((m) => {
          const scoped = tools.filter(toolInTeam);
          const src = m === 'empty' ? [] : scoped;
          const enabled = src.filter((t) => t.enabled);
          const busiest = [...enabled].sort((a, b) => b.calls24h - a.calls24h)[0];
          return {
            ...list(scoped, p, { text: (t) => `${t.name} ${t.description} ${t.system}`, value: field, facetKeys: ['access', 'type', 'system'] }, m),
            stats: {
              total: src.length,
              disabled: src.length - enabled.length,
              systems: new Set(src.map((t) => t.system)).size,
              calls24h: enabled.reduce((s, t) => s + t.calls24h, 0),
              callsTrendPct: 11,
              busiest: busiest?.name ?? '—',
              requireReview: src.filter((t) => t.requiresReview).length,
              noisy: src.filter((t) => t.errorRate >= 0.02).map((t) => t.name),
            },
          };
        }),
      create: (input) =>
        respond(() => {
          if (tools.some((t) => t.name === input.name)) throw new ApiError(`A tool named ${input.name} already exists.`, 409);
          const t: Tool = { id: id('tl'), ...input, requiresReview: input.access === 'money_movement' || input.requiresReview, enabled: false, calls24h: 0, errorRate: 0, p95Ms: 0, grantedAgentIds: [], sampleInput: '{\n  \n}' };
          tools.unshift(t);
          return t;
        }),
      update: (tid, input) =>
        respond(() => {
          const t = tools.find((x) => x.id === tid) ?? notFound('Tool');
          Object.assign(t, input);
          if (t.access === 'money_movement') t.requiresReview = true;
          return t;
        }),
      remove: (tid) =>
        respond(() => {
          const i = tools.findIndex((x) => x.id === tid);
          if (i < 0) notFound('Tool');
          for (const a of agents) a.toolIds = a.toolIds.filter((x) => x !== tid);
          tools.splice(i, 1);
        }),
      test: (tid, input) =>
        respond(() => {
          const t = tools.find((x) => x.id === tid) ?? notFound('Tool');
          let parsed: unknown;
          try {
            parsed = JSON.parse(input);
          } catch {
            return { ok: false, status: 400, tookMs: 4, output: JSON.stringify({ error: 'Input is not valid JSON' }, null, 2) };
          }
          return { ok: true, status: 200, tookMs: t.p95Ms ? Math.round(t.p95Ms * 0.6) : 90, output: JSON.stringify({ tool: t.name, sandbox: true, received: parsed, result: 'ok' }, null, 2) };
        }),
      bulkUpdate: (ids, patch) =>
        respond(() =>
          bulk(ids, (tid) => {
            const t = tools.find((x) => x.id === tid);
            if (!t) return 'Not found';
            if (patch.requiresReview === false && t.access === 'money_movement') return 'Moves money; review stays on';
            Object.assign(t, patch);
          }),
        ),
      bulkRemove: (ids) =>
        respond(() =>
          bulk(ids, (tid) => {
            const i = tools.findIndex((x) => x.id === tid);
            if (i < 0) return 'Not found';
            if (tools[i].grantedAgentIds.length) return `Granted to ${tools[i].grantedAgentIds.length === 1 ? '1 agent' : `${tools[i].grantedAgentIds.length} agents`}`;
            tools.splice(i, 1);
          }),
        ),
    },
  };
  // Evals start a run on every agent save; model risk adds the eval gate to publish requests and decides validations.
  Object.assign(self, { agents: evals.wrapAgents(self.agents), reviews: modelRisk.wrapReviews(self.reviews) });
  return self;
}
