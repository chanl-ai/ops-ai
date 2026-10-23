'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api, brand } from '@/lib/api';
import type {
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
import type { AgentFilters, DeploymentFilters, ListParams, PolicyFilters, ReviewListParams, RunFilters, ToolFilters, WorkflowFilters } from '@/lib/types/query';
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

export const useOverview = () => useTeamQuery({ queryKey: qk.overview, queryFn: api.overview.get });
/** The demo brand from the console's env, when one is set. */
export const useBrand = () => brand;

export const useLookups = () => useTeamQuery({ queryKey: qk.lookups, queryFn: api.lookups.get, staleTime: 5 * 60_000 });

export const useAgents = (p: ListParams<AgentFilters>, opts: { enabled?: boolean } = {}) => usePagedQuery({ queryKey: qk.agents(p), queryFn: () => api.agents.list(p), ...opts });
export const useAgent = (id: string) => useTeamQuery({ queryKey: qk.agent(id), queryFn: () => api.agents.get(id) });
export const useWorkflows = (p: ListParams<WorkflowFilters>) => usePagedQuery({ queryKey: qk.workflows(p), queryFn: () => api.workflows.list(p) });
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
export const useReviewPlace = (id: string | null) => useTeamQuery({ queryKey: ['reviews', 'place', id], queryFn: () => api.reviews.place(id!), enabled: !!id });
export const useReviewByRunKey = (runKey: string | null) =>
  useTeamQuery({ queryKey: ['reviews', 'run-key', runKey], queryFn: () => api.reviews.byRunKey(runKey!), enabled: !!runKey });
export const useReviews = (p: ReviewListParams) => usePagedQuery({ queryKey: qk.reviews(p), queryFn: () => api.reviews.list(p) });
/** The sidebar badge reads the same list endpoint and view count as the Reviews page, so the two never disagree. */
export const useOpenReviewCount = () => useTeamQuery({ queryKey: ['reviews', 'open-count'], queryFn: () => api.reviews.list({ view: 'open', page: 1, pageSize: 1 }), select: (r) => r.viewCounts.open });
export const usePolicies = (p: ListParams<PolicyFilters>) => usePagedQuery({ queryKey: qk.policies(p), queryFn: () => api.policies.list(p) });
export const useTools = (p: ListParams<ToolFilters>) => usePagedQuery({ queryKey: qk.tools(p), queryFn: () => api.tools.list(p) });

/** Invalidates the given roots after a successful write so every list and count refreshes. */
function useWrite<A, R>(fn: (a: A) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}

export const useCreateAgent = () => useWrite((i: AgentInput) => api.agents.create(i), ['agents', 'overview']);
export const useUpdateAgent = (id: string) =>
  useWrite((p: AgentPatch) => api.agents.update(id, p), ['agents', 'agent', 'tools', 'kbs']);
export const useDeleteAgent = () => useWrite((id: string) => api.agents.remove(id), ['agents', 'overview']);
export const useAgentVersions = (id: string) => useTeamQuery({ queryKey: qk.agentVersions(id), queryFn: () => api.agents.versions(id) });
export const useAgentRuns = (id: string) => useTeamQuery({ queryKey: qk.agentRuns(id), queryFn: () => api.agents.runs(id) });
export const useRestoreAgent = (id: string) => useWrite((v: number) => api.agents.restore(id, v), ['agents', 'agent']);
/** Opens an `agent_publish` review, so Reviews, Overview and Assurance refresh too. */
export const useRequestAgentPublish = (id: string) =>
  useWrite(({ version, note }: { version: number; note: string }) => api.agents.requestPublish(id, version, note), ['agents', 'agent', 'reviews', 'overview', 'assurance', 'notifications']);
/** Asked when the publish dialog opens, so it says whether the publish waits for review before anyone presses it. */
export const useAgentPublishPreview = (id: string, version: number, enabled: boolean) =>
  useTeamQuery({ queryKey: ['agent', id, 'publish-preview', version], queryFn: () => api.agents.publishPreview(id, version), enabled, staleTime: 0 });
export const useAgentPaused = (id: string) => useWrite((paused: boolean) => api.agents.setPaused(id, paused), ['agents', 'agent', 'overview']);
/** The tools an agent may be granted; the catalogue changes only with the runtime. */
export const useModelAliases = () => useTeamQuery({ queryKey: ['agent-model-aliases'], queryFn: () => api.agents.modelAliases(), staleTime: 5 * 60_000 });
export const useGuardrails = () => useTeamQuery({ queryKey: ['agent-guardrails'], queryFn: () => api.guardrails.list(), staleTime: 60_000 });
// Under the same key as the whole list, so the guardrail writes' invalidation refreshes the page too.
export const useGuardrailsPage = (p: ListParams) => usePagedQuery({ queryKey: ['agent-guardrails', 'page', p], queryFn: () => api.guardrails.page(p) });
export const useGuardrail = (id: string) => useTeamQuery({ queryKey: ['agent-guardrails', 'one', id], queryFn: () => api.guardrails.get(id) });
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
  usePagedQuery({ queryKey: qk.workflowRuns(id, p), queryFn: () => api.workflows.runs(id, p) });
export const useWorkflowVersions = (id: string) => useTeamQuery({ queryKey: qk.workflowVersions(id), queryFn: () => api.workflows.versions(id) });
export const useBulkUpdateWorkflows = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { status?: LifecycleStatus; owner?: string } }) => api.workflows.bulkUpdate!(ids, patch), ['workflows', 'overview']);
/** Whether the workflows backend has bulk routes; the list hides its bulk actions when it does not. */
export const workflowsBulkSupported = !!api.workflows.bulkUpdate;

export const useDecideReview = () =>
  useWrite(({ id, ...i }: ReviewDecisionInput & { id: string }) => api.reviews.decide(id, i), ['reviews', 'cases', 'overview', 'model-risk', 'logs', 'skills', 'templates', 'notifications', 'assurance', 'agent', 'agents']);
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
