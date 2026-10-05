'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
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
  workflowRuns: (id: string, p?: unknown) => ['workflow', id, 'runs', p] as const,
  workflowVersions: (id: string) => ['workflow', id, 'versions'] as const,
};

/** Paged lists keep the previous page on screen while the next one loads. */
const paged = { placeholderData: keepPreviousData };

export const useOverview = () => useQuery({ queryKey: qk.overview, queryFn: api.overview.get });
export const useLookups = () => useQuery({ queryKey: qk.lookups, queryFn: api.lookups.get, staleTime: 5 * 60_000 });

export const useAgents = (p: ListParams<AgentFilters>) => useQuery({ queryKey: qk.agents(p), queryFn: () => api.agents.list(p), ...paged });
export const useAgent = (id: string) => useQuery({ queryKey: qk.agent(id), queryFn: () => api.agents.get(id) });
export const useWorkflows = (p: ListParams<WorkflowFilters>) => useQuery({ queryKey: qk.workflows(p), queryFn: () => api.workflows.list(p), ...paged });
export const useWorkflow = (id: string) => useQuery({ queryKey: qk.workflow(id), queryFn: () => api.workflows.get(id) });
export const useReview = (id: string | null) => useQuery({ queryKey: ['reviews', 'one', id], queryFn: () => api.reviews.get(id!), enabled: !!id });
export const useReviews = (p: ReviewListParams) => useQuery({ queryKey: qk.reviews(p), queryFn: () => api.reviews.list(p), ...paged });
/** The sidebar badge reads the same list endpoint and view count as the Reviews page, so the two never disagree. */
export const useOpenReviewCount = () => useQuery({ queryKey: ['reviews', 'open-count'], queryFn: () => api.reviews.list({ view: 'open', page: 1, pageSize: 1 }), select: (r) => r.viewCounts.open });
export const usePolicies = (p: ListParams<PolicyFilters>) => useQuery({ queryKey: qk.policies(p), queryFn: () => api.policies.list(p), ...paged });
export const useTools = (p: ListParams<ToolFilters>) => useQuery({ queryKey: qk.tools(p), queryFn: () => api.tools.list(p), ...paged });

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
export const useAgentVersions = (id: string) => useQuery({ queryKey: qk.agentVersions(id), queryFn: () => api.agents.versions(id) });
export const useRestoreAgent = (id: string) => useWrite((v: number) => api.agents.restore(id, v), ['agents', 'agent']);
export const useAgentStatus = (id: string) => useWrite((s: LifecycleStatus) => api.agents.setStatus(id, s), ['agents', 'agent', 'overview']);
export const useTestAgent = (id: string) => useMutation({ mutationFn: ({ message, runAsId }: { message: string; runAsId?: string }) => api.agents.test(id, message, runAsId) });
export const useBulkUpdateAgents = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { status?: LifecycleStatus; owner?: string } }) => api.agents.bulkUpdate(ids, patch), ['agents', 'agent', 'overview']);
export const useBulkDeleteAgents = () => useWrite((ids: string[]) => api.agents.bulkRemove(ids), ['agents', 'overview', 'tools']);

export const useCreateWorkflow = () => useWrite((i: WorkflowInput) => api.workflows.create(i), ['workflows', 'lookups']);
export const useValidateWorkflow = (id: string) =>
  useWrite(({ graph, target }: { graph: WorkflowGraph; target?: 'draft' | 'live' }) => api.workflows.validate(id, graph, target), ['workflow']);
/** Autosaves the canvas draft; writes the result straight into the cached workflow so returning to the page shows it. */
export const useSaveDraft = (id: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (graph: WorkflowGraph | null) => api.workflows.saveDraft(id, graph),
    onSuccess: (draft) => qc.setQueryData(qk.workflow(id), (w: WorkflowDetail | undefined) => (w ? { ...w, draft: draft ?? undefined } : w)),
  });
};
export const useLastValidation = (id: string) => useQuery({ queryKey: ['workflow', id, 'validation'], queryFn: () => api.workflows.lastValidation(id) });
export const useRequestPublish = (id: string) =>
  useWrite((i: { graph: WorkflowGraph; note: string; validationRunId?: string; checksFailing: number }) => api.workflows.requestPublish(id, i), ['workflows', 'workflow', 'reviews', 'overview']);

export const useDeployments = (p: ListParams<DeploymentFilters>) => useQuery({ queryKey: ['deployments', p], queryFn: () => api.deployments.list(p), ...paged });
export const useCreateDeployment = () => useWrite((i: DeploymentInput) => api.deployments.create(i), ['deployments', 'workflows', 'workflow']);
export const useUpdateDeployment = () => useWrite(({ id, ...p }: DeploymentPatch & { id: string }) => api.deployments.update(id, p), ['deployments']);
export const useDeleteDeployment = () => useWrite((id: string) => api.deployments.remove(id), ['deployments', 'workflows', 'workflow']);
export const usePromoteDeployment = () => useWrite(({ id, ...i }: { id: string; name: string; allowedDomains?: string[] }) => api.deployments.promote(id, i), ['deployments', 'workflows', 'workflow']);
export const useRotateKey = () => useWrite((id: string) => api.deployments.rotateKey(id), ['deployments']);
export const useBulkUpdateDeployments = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { status?: 'active' | 'paused'; toLatest?: boolean } }) => api.deployments.bulkUpdate(ids, patch), ['deployments']);
export const useBulkDeleteDeployments = () => useWrite((ids: string[]) => api.deployments.bulkRemove(ids), ['deployments', 'workflows', 'workflow']);

export const useTests = (workflowId: string) => useQuery({ queryKey: ['workflow', workflowId, 'tests'], queryFn: () => api.tests.list(workflowId) });
export const useCreateTest = (workflowId: string) => useWrite((i: TestCaseInput) => api.tests.create(workflowId, i), ['workflow']);
export const useImportTests = (workflowId: string) => useWrite((rows: TestCaseInput[]) => api.tests.importRows(workflowId, rows), ['workflow']);
export const useTestFromRun = () => useWrite((runId: string) => api.tests.fromRun(runId), ['workflow']);
export const useDeleteTest = () => useWrite((id: string) => api.tests.remove(id), ['workflow']);
export const useUpdateWorkflow = (id: string) => useWrite((i: WorkflowSettingsInput) => api.workflows.update(id, i), ['workflows', 'workflow', 'lookups', 'reviews']);
export const useWorkflowStatus = (id: string) => useWrite((s: LifecycleStatus) => api.workflows.setStatus(id, s), ['workflows', 'workflow', 'overview']);
export const useDeleteWorkflow = () => useWrite((id: string) => api.workflows.remove(id), ['workflows', 'lookups', 'overview']);
export const useRestoreWorkflow = (id: string) => useWrite((v: number) => api.workflows.restore(id, v), ['workflows', 'workflow']);
export const useWorkflowRuns = (id: string, p: ListParams<RunFilters>) =>
  useQuery({ queryKey: qk.workflowRuns(id, p), queryFn: () => api.workflows.runs(id, p), ...paged });
export const useWorkflowVersions = (id: string) => useQuery({ queryKey: qk.workflowVersions(id), queryFn: () => api.workflows.versions(id) });
export const useBulkUpdateWorkflows = () =>
  useWrite(({ ids, patch }: { ids: string[]; patch: { status?: LifecycleStatus; owner?: string } }) => api.workflows.bulkUpdate(ids, patch), ['workflows', 'overview']);

export const useDecideReview = () =>
  useWrite(({ id, ...i }: ReviewDecisionInput & { id: string }) => api.reviews.decide(id, i), ['reviews', 'overview', 'model-risk', 'logs']);
export const useAssignReviews = () => useWrite(({ ids, assignee }: { ids: string[]; assignee?: string }) => api.reviews.assign(ids, assignee), ['reviews']);
export const useBulkDecideReviews = () =>
  useWrite(({ ids, decision, reason }: { ids: string[]; decision: ReviewDecision; reason?: string }) => api.reviews.bulkDecide(ids, decision, reason), ['reviews', 'overview']);

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
