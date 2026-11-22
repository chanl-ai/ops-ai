'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api, brand } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';
import type { ToolRowFilters } from '@/lib/types/tool-directory';
import type {
  Agent,
  AgentInput,
  AgentPatch,
  GatePolicyInput,
  ReviewDecisionInput,
  ToolInput,
  WorkflowGraph,
  DeploymentInput,
  DeploymentPatch,
  LifecycleStatus,
  TestCaseInput,
  ReviewDecision,
  WorkflowDetail,
  WorkflowInput,
  WorkflowSettingsInput,
} from '@/lib/types/domain';
import type { AgentFilters, DeploymentFilters, ListParams, ListResult, PolicyFilters, ReviewListParams, RunFilters, ToolFilters, WorkflowFilters } from '@/lib/types/query';
import { knowledgeChange, toolChange } from '@/lib/agent-tools';
import { baseOf, staleSave } from '@/lib/save-base';
import { teamKey, useTeamQuery } from './team-query';

export const qk = {
  overview: ['overview'] as const,
  lookups: ['lookups'] as const,
  agents: (p?: unknown) => ['agents', p] as const,
  agent: (id: string) => ['agent', id] as const,
  workflows: (p?: unknown) => ['workflows', p] as const,
  workflow: (id: string) => ['workflow', id] as const,
  reviews: (p?: unknown) => ['reviews', p] as const,
  policies: (p?: unknown) => ['policies', p] as const,
  tools: (p?: unknown) => ['tools', p] as const,
  agentVersions: (id: string) => ['agent', id, 'versions'] as const,
  agentRuns: (id: string) => ['agent', id, 'runs'] as const,
  workflowRuns: (id: string, p?: unknown) => ['workflow', id, 'runs', p] as const,
  workflowVersions: (id: string) => ['workflow', id, 'versions'] as const,
};

// The sidebar reads it on every page (its count and the Human Tasks badge), so moving between pages reuses the answer.
export const useOverview = () => useTeamQuery({ queryKey: qk.overview, queryFn: api.overview.get, staleTime: 30_000 });
/** The demo brand from the console's env, when one is set. */
export const useBrand = () => brand;

export const useLookups = () => useTeamQuery({ queryKey: qk.lookups, queryFn: api.lookups.get, staleTime: 5 * 60_000 });

/** A row of the agents list, as `GET /v1/agents` answers it. */
export type AgentRow = Awaited<ReturnType<OpsAI['raw']['agents']['agents_list_agents']>>['data'][number];

/** One page of the team's agents; the filters, search, sort and paging go to the route. `ids` names the agents a stored choice holds. */
export const fetchAgents = (p: ListParams<AgentFilters> & { ids?: string[] }) =>
  sdk((ops) =>
    ops.raw.agents.agents_list_agents({
      query: {
        page: p.page,
        pageSize: p.pageSize,
        search: p.search || undefined,
        sortBy: p.sortBy,
        sortOrder: p.sortOrder,
        ids: p.ids?.length ? p.ids : undefined,
        availability: p.filters?.availability?.length ? p.filters.availability : undefined,
        teamId: p.filters?.teamId?.length ? p.filters.teamId : undefined,
      },
    }),
  );
export const useAgents = (p: ListParams<AgentFilters>, opts: { enabled?: boolean } = {}) => usePagedQuery({ queryKey: qk.agents(p), queryFn: () => fetchAgents(p), ...opts });
export const useAgent = (id: string) => useTeamQuery({ queryKey: qk.agent(id), queryFn: () => api.agents.get(id) });
/** A row of the workflows list, as `GET /v1/workflows` answers it. */
export type WorkflowRow = Awaited<ReturnType<OpsAI['raw']['agents']['workflows_list_workflows']>>['data'][number] & {
  /** The route does not return the wrapped agent's name yet; pickers fall back to the workflow's name. */
  wrapsAgentName?: string;
};

/** One page of the current engine's workflows; the filters, search and sort go to the route. */
export const fetchWorkflows = (p: ListParams<WorkflowFilters> & { ids?: string[] }): Promise<ListResult<WorkflowRow>> =>
  sdk((ops) =>
    ops.raw.agents.workflows_list_workflows({
      query: {
        page: p.page,
        pageSize: p.pageSize,
        search: p.search || undefined,
        sortBy: p.sortBy,
        sortOrder: p.sortOrder,
        ids: p.ids?.length ? p.ids : undefined,
        status: p.filters?.status?.length ? p.filters.status : undefined,
        startable: p.filters?.startable?.includes('true') || undefined,
        takesFiles: p.filters?.takesFiles?.includes('true') || undefined,
        engine: 'current',
      },
    }),
  );
export const useWorkflows = (p: ListParams<WorkflowFilters>) => usePagedQuery({ queryKey: qk.workflows(p), queryFn: () => fetchWorkflows(p) });
export const useWorkflow = (id: string) => useTeamQuery({ queryKey: qk.workflow(id), queryFn: () => api.workflows.get(id) });
// While a typed task's AI assist is still being written (its region says pending: true), the task is read again every
// 2 s. The server drops the region once an assist runs past its limit, which ends the polling.
export const useReview = (id: string | null) =>
  useTeamQuery({
    queryKey: ['reviews', 'one', id],
    queryFn: () => api.reviews.get(id!),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.task?.regions.some((r) => r.region === 'assist' && (r.data as { pending?: unknown } | null)?.pending === true) ? 2000 : false),
  });
/** The task's place in the open queue ("5 of 24") and its neighbours, from the server. */
export const useReviewPlace = (id: string | null, opts?: { view?: string; group?: 'case' }) =>
  useTeamQuery({ queryKey: ['reviews', 'place', id, opts?.view ?? 'open', opts?.group ?? null], queryFn: () => api.reviews.place(id!, opts), enabled: !!id });
export const useReviewByRunKey = (runKey: string | null) =>
  useTeamQuery({ queryKey: ['reviews', 'run-key', runKey], queryFn: () => api.reviews.byRunKey(runKey!), enabled: !!runKey });
export const useReviews = (p: ReviewListParams) => usePagedQuery({ queryKey: qk.reviews(p), queryFn: () => api.reviews.list(p) });
/** The sidebar badge reads the same list endpoint and view count as the Reviews page, so the two never disagree. */
export const useOpenReviewCount = () => useTeamQuery({ queryKey: ['reviews', 'open-count'], queryFn: () => api.reviews.list({ view: 'open', page: 1, pageSize: 1 }), select: (r) => r.viewCounts.open });
export const usePolicies = (p: ListParams<PolicyFilters>) => usePagedQuery({ queryKey: qk.policies(p), queryFn: () => api.policies.list(p) });
export const useTools = (p: ListParams<ToolFilters>) => usePagedQuery({ queryKey: qk.tools(p), queryFn: () => api.tools.list(p) });
/** Every tool the team can use, one row each, as the Tools page lists them. */
export const useToolDirectory = (p: ListParams<ToolRowFilters>) => usePagedQuery({ queryKey: ['tools', 'directory', p], queryFn: () => api.tools.directory(p) });
/** One tool's row, for its page's Used by. */
export const useToolRow = (id: string | null) => useTeamQuery({ queryKey: ['tools', 'one', id], queryFn: () => api.tools.one(id!), enabled: !!id });

/** Invalidates the given roots after a successful write so every list and count refreshes. */
function useWrite<A, R>(fn: (a: A) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}

export const useCreateAgent = () => useWrite((i: AgentInput) => api.agents.create(i), ['agents', 'overview']);
/** Saves fields on the agent's draft, made on `base`: the agent as the page last read it. */
export const useUpdateAgent = (id: string) =>
  useWrite(({ base, ...fields }: AgentPatch & { base: Agent }) => api.agents.update(id, { ...fields, ...baseOf(base) }), ['agents', 'agent', 'tools', 'kbs']);
/**
 * The one way the console changes an agent's tool list or knowledge list outside an @ insert: the stored agent is
 * read, `change` is made on it and saved naming the copy it was read from, so a change made from a list the page
 * showed a moment ago never drops an item saved since. A save that lands in between is refused, and the change is
 * made once more on the newer copy.
 */
async function changeStoredAgent(agentId: string, change: (stored: Agent) => AgentPatch | null): Promise<Agent> {
  const once = async () => {
    const agent = await api.agents.get(agentId);
    const fields = change(agent);
    return fields ? api.agents.update(agentId, { ...fields, ...baseOf(agent) }) : agent;
  };
  return once().catch((e: unknown) => (staleSave(e) ? once() : Promise.reject(e)));
}
type ListChange = { add?: string[]; remove?: string[] };
const changeAgentTools = (agentId: string, change: ListChange) => changeStoredAgent(agentId, (a) => toolChange(a, change));
/** Reads the open agent again, after a save was refused because a newer copy exists. */
export function useReadAgentAgain() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['agent'] });
}
/** Grants and removes tools on the agent page; lands in the agent's draft. */
export const useChangeAgentTools = (agentId: string) => useWrite((change: ListChange) => changeAgentTools(agentId, change), ['agents', 'agent', 'tools', 'kbs']);
/** Adds and removes knowledge bases on the agent page; lands in the agent's draft. */
export const useChangeAgentKnowledge = (agentId: string) =>
  useWrite((change: ListChange) => changeStoredAgent(agentId, (a) => knowledgeChange(a, change)), ['agents', 'agent', 'kbs']);
/** Grants one tool to an agent from the tool's side. The app page's and Tools page's Used by refresh too. */
export const useGrantToolToAgent = () =>
  useWrite(({ agentId, toolId }: { agentId: string; toolId: string }) => changeAgentTools(agentId, { add: [toolId] }), ['agents', 'agent', 'tools', 'apps']);
export const useDeleteAgent = () => useWrite((id: string) => api.agents.remove(id), ['agents', 'overview']);
export const useAgentVersions = (id: string) => useTeamQuery({ queryKey: qk.agentVersions(id), queryFn: () => api.agents.versions(id) });
export const useAgentRuns = (id: string) => useTeamQuery({ queryKey: qk.agentRuns(id), queryFn: () => api.agents.runs(id) });
export const useRestoreAgent = (id: string) => useWrite((v: number) => api.agents.restore(id, v), ['agents', 'agent']);
/** Opens an `agent_publish` review, so Reviews, Overview and Assurance refresh too. */
export const useRequestAgentPublish = (id: string) =>
  useWrite(({ version, note, follows }: { version: number; note: string; follows?: string }) => api.agents.requestPublish(id, version, note, follows), ['agents', 'agent', 'reviews', 'overview', 'assurance', 'notifications']);
/** Asked when the publish dialog opens, so it says whether the publish waits for review before anyone presses it. */
export const useAgentPublishPreview = (id: string, version: number, enabled: boolean) =>
  useTeamQuery({ queryKey: ['agent', id, 'publish-preview', version], queryFn: () => api.agents.publishPreview(id, version), enabled, staleTime: 0 });
/** The prompt the model reads for a version, for View prompt; asked only while the dialog is open. */
export const useAgentPrompt = (id: string, version: number, enabled: boolean) =>
  useTeamQuery({ queryKey: ['agent', id, 'prompt', version], queryFn: () => api.agents.promptView(id, version), enabled, staleTime: 0 });
/** A proposed text per brief heading for the Draft dialog; writes nothing, so nothing is refetched after it. */
export const useDraftBrief = (id: string) => useMutation({ mutationFn: (description: string) => api.agents.draftBrief(id, description) });
/** What stops the newest draft from publishing and where; read when the publish dialog opens and after each save. */
export const useAgentPublishCheck = (id: string, version: number, enabled = true) =>
  useTeamQuery({ queryKey: ['agent', id, 'publish-check', version], queryFn: () => api.agents.publishCheck(id, version), enabled, staleTime: 0 });
export const useAgentPaused = (id: string) => useWrite((paused: boolean) => api.agents.setPaused(id, paused), ['agents', 'agent', 'overview']);
/** The tools an agent may be granted; the catalogue changes only with the runtime. */
/**
 * The models an agent may run on, a side read: asked only where a model is chosen (`enabled`), and a failure shows
 * there, never as the page-wide "can't reach" banner.
 */
export const useModelAliases = (enabled = true) =>
  useTeamQuery({ queryKey: ['agent-model-aliases'], queryFn: () => api.agents.modelAliases(), staleTime: 5 * 60_000, enabled, meta: { side: true } });
export const useGrantableTools = () => useTeamQuery({ queryKey: ['agent-grantable-tools'], queryFn: () => api.agents.grantableTools(), staleTime: 5 * 60_000 });
export const useBulkUpdateAgents = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { paused?: boolean; owner?: string } }) => api.agents.bulkUpdate!(ids, patch), ['agents', 'agent', 'overview']);
export const useBulkDeleteAgents = () => useWrite((ids: string[]) => api.agents.bulkRemove!(ids), ['agents', 'overview', 'tools']);
/** Whether the agents backend has bulk routes; the list hides its bulk actions when it does not. */
export const agentsBulkSupported = !!api.agents.bulkUpdate && !!api.agents.bulkRemove;

/** The fields and operators a branch may route on; they change only with the runtime, so they are fetched once. */
export const useRouteFields = () => useTeamQuery({ queryKey: ['workflow-route-fields'], queryFn: () => api.workflows.routeFields(), staleTime: Infinity });
/** One test run of the draft on a sample case; writes nothing, so nothing is invalidated. */
export const useTestWorkflow = (id: string) => useMutation({ mutationFn: (graph?: WorkflowGraph) => api.workflows.test(id, { graph }) });
export const useCreateWorkflow = () => useWrite((i: WorkflowInput) => api.workflows.create(i), ['workflows', 'lookups']);
export const useValidateWorkflow = (id: string) =>
  useWrite(({ graph, target }: { graph: WorkflowGraph; target?: 'draft' | 'live' }) => api.workflows.validate(id, graph, target), ['workflow']);
/** Autosaves the canvas draft; writes the result straight into the cached workflow so returning to the page shows it. */
export const useSaveDraft = (id: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (graph: WorkflowGraph | null) => api.workflows.saveDraft(id, graph),
    onSuccess: (draft) => qc.setQueryData(teamKey(qk.workflow(id)), (w: WorkflowDetail | undefined) => (w ? { ...w, draft: draft ?? undefined } : w)),
  });
};
export const useLastValidation = (id: string) => useTeamQuery({ queryKey: ['workflow', id, 'validation'], queryFn: () => api.workflows.lastValidation(id) });
export const useRequestPublish = (id: string) =>
  useWrite((i: { graph: WorkflowGraph; note: string; validationRunId?: string; checksFailing: number }) => api.workflows.requestPublish(id, i), ['workflows', 'workflow', 'reviews', 'overview']);

export const useDeployments = (p: ListParams<DeploymentFilters>) => usePagedQuery({ queryKey: ['deployments', p], queryFn: () => api.deployments.list(p) });
export const useCreateDeployment = () => useWrite((i: DeploymentInput) => api.deployments.create(i), ['deployments', 'workflows', 'workflow']);
export const useUpdateDeployment = () => useWrite(({ id, ...p }: DeploymentPatch & { id: string }) => api.deployments.update(id, p), ['deployments']);
export const useDeleteDeployment = () => useWrite((id: string) => api.deployments.remove(id), ['deployments', 'workflows', 'workflow']);
export const usePromoteDeployment = () => useWrite(({ id, ...i }: { id: string; name: string; allowedDomains?: string[] }) => api.deployments.promote(id, i), ['deployments', 'workflows', 'workflow']);
export const useRotateKey = () => useWrite((id: string) => api.deployments.rotateKey(id), ['deployments']);
export const useBulkUpdateDeployments = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { status?: 'active' | 'paused'; toLatest?: boolean } }) => api.deployments.bulkUpdate(ids, patch), ['deployments']);
export const useBulkDeleteDeployments = () => useWrite((ids: string[]) => api.deployments.bulkRemove(ids), ['deployments', 'workflows', 'workflow']);

export const useTests = (workflowId: string) => useTeamQuery({ queryKey: ['workflow', workflowId, 'tests'], queryFn: () => api.tests.list(workflowId) });
export const useCreateTest = (workflowId: string) => useWrite((i: TestCaseInput) => api.tests.create(workflowId, i), ['workflow']);
export const useImportTests = (workflowId: string) => useWrite(({ rows, fileId }: { rows: TestCaseInput[]; fileId?: string }) => api.tests.importRows(workflowId, rows, fileId), ['workflow', 'files']);
export const useTestFromRun = () => useWrite((runId: string) => api.tests.fromRun(runId), ['workflow']);
export const useDeleteTest = () => useWrite((id: string) => api.tests.remove(id), ['workflow']);
export const useUpdateWorkflow = (id: string) => useWrite((i: WorkflowSettingsInput) => api.workflows.update(id, i), ['workflows', 'workflow', 'lookups', 'reviews']);
export const useWorkflowStatus = (id: string) => useWrite((s: LifecycleStatus) => api.workflows.setStatus(id, s), ['workflows', 'workflow', 'overview']);
export const useDeleteWorkflow = () => useWrite((id: string) => api.workflows.remove(id), ['workflows', 'lookups', 'overview']);
export const useRestoreWorkflow = (id: string) => useWrite((v: number) => api.workflows.restore(id, v), ['workflows', 'workflow']);
export const useWorkflowRuns = (id: string, p: ListParams<RunFilters>) =>
  usePagedQuery({ queryKey: qk.workflowRuns(id, p), queryFn: () =>
      sdk((ops) => ops.raw.agents.workflows_list_runs({ path: { workflow_id: id }, query: { page: p.page, pageSize: p.pageSize, status: p.filters?.status?.length ? p.filters.status : undefined } })),
  });
export const useWorkflowVersions = (id: string) => useTeamQuery({ queryKey: qk.workflowVersions(id), queryFn: () => api.workflows.versions(id) });
export const useBulkUpdateWorkflows = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { status?: LifecycleStatus; owner?: string } }) => api.workflows.bulkUpdate!(ids, patch), ['workflows', 'overview']);
/** Whether the workflows backend has bulk routes; the list hides its bulk actions when it does not. */
export const workflowsBulkSupported = !!api.workflows.bulkUpdate;

export const useDecideReview = () =>
  useWrite(({ id, ...i }: ReviewDecisionInput & { id: string }) => api.reviews.decide(id, i), ['reviews', 'cases', 'overview', 'model-risk', 'logs', 'skills', 'templates', 'notifications', 'assurance', 'agent', 'agents']);
/** Takes back the person's own waiting publish request; the version reads as a draft again. */
export const useWithdrawReview = () => useWrite((id: string) => api.reviews.withdraw(id), ['reviews', 'agent', 'agents', 'skill', 'skills', 'workflow', 'workflows', 'engine', 'overview', 'notifications']);
export const useAssignReviews = () => useWrite(({ ids, assignee }: { ids: string[]; assignee?: string }) => api.reviews.assign(ids, assignee), ['reviews']);
export const useBulkDecideReviews = () =>
  useWrite(({ ids, decision, reason, stepUpToken }: { ids: string[]; decision: ReviewDecision; reason?: string; stepUpToken?: string }) => api.reviews.bulkDecide(ids, decision, reason, { stepUpToken }), ['reviews', 'overview']);

export const useCreatePolicy = () => useWrite((i: GatePolicyInput) => api.policies.create(i), ['policies']);
export const useUpdatePolicy = () => useWrite(({ id, ...i }: GatePolicyInput & { id: string }) => api.policies.update(id, i), ['policies', 'reviews']);
export const useDeletePolicy = () => useWrite((id: string) => api.policies.remove(id), ['policies']);
export const useBulkUpdatePolicies = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { sla?: string; reviewers?: string } }) => api.policies.bulkUpdate(ids, patch), ['policies', 'reviews']);
export const useBulkDeletePolicies = () => useWrite((ids: string[]) => api.policies.bulkRemove(ids), ['policies']);

export const useCreateTool = () => useWrite((i: ToolInput) => api.tools.create(i), ['tools']);
export const useUpdateTool = () => useWrite(({ id, ...i }: Partial<ToolInput> & { id: string; enabled?: boolean }) => api.tools.update(id, i), ['tools']);
export const useDeleteTool = () => useWrite((id: string) => api.tools.remove(id), ['tools', 'agent']);
export const useBulkUpdateTools = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { enabled?: boolean; requiresReview?: boolean } }) => api.tools.bulkUpdate(ids, patch), ['tools']);
export const useBulkDeleteTools = () => useWrite((ids: string[]) => api.tools.bulkRemove(ids), ['tools']);
export const useTestTool = () => useMutation({ mutationFn: ({ id, input }: { id: string; input: string }) => api.tools.test(id, input) });
