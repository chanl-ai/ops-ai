import type { Tool } from '@/lib/types/domain';
import type { ListParams } from '@/lib/types/query';

import { optionsQs } from './options';
import { ApiError, type OpsApi } from './contract';
import type { CasesApi } from './cases-contract';
import { createCasesHttp } from './cases-http';
import { createChatHttp } from './chat-http';
import { createChannelsHttp } from './channels-http';
import { createEngineHttp } from './engine-http';
import { createKnowledgeHttp } from './knowledge-http';
import { createKnowledgeChangesHttp } from './knowledge-changes-http';
import { createNotificationsHttp } from './notifications-http';
import { createSearchHttp } from './search-http';
import type { GovernanceApi } from './governance-contract';
import { createExecutionsHttp, createGovernanceHttp } from './governance-http';
import { createSettingsHttp } from './settings-http';
import { createSignInPolicyHttp } from './sign-in-http';
import { createInvitesHttp } from './invites-http';
import { createAccountHttp } from './account-http';
import { createWorkspacePoliciesHttp } from './workspace-policies-http';
import { createProviderKeysHttp } from './provider-keys-http';
import { createSignInProvidersHttp } from './sign-in-providers-http';
import { createWorkspaceTeamsHttp } from './workspace-teams-http';
import { createEvalsHttp } from './evals-http';
import { createModelRiskHttp } from './model-risk-http';
import { createToolModulesHttp } from './tool-modules-http';
import { createEgressHttp } from './egress-http';
import { createSecretsHttp } from './secrets-http';
import { createConnectionsHttp } from './connections-http';
import { createIntegrationsHttp } from './integrations-http';
import { createFilesHttp } from './files-http';
import { createTemplatesHttp } from './templates-http';
import { createPromptsHttp } from './prompts-http';
import { createGuardrailsHttp } from './guardrails-http';
import { createSkillsHttp } from './skills-http';
import { createWidgetDeploymentsHttp } from './widget-deployments-http';
import { createBatchesHttp } from './batches-http';
import { createFormsHttp } from './forms-http';
import { createActivityHttp } from './activity-http';
import { createCaseRecordsHttp } from './case-records-http';
import { createWidgetsHttp } from './widgets-http';
import { createAssuranceHttp } from './assurance-http';
import { createConnectHttp } from './connect-http';
import { createWikiHttp } from './wiki-http';
import { fetchWithIdentity } from './request-identity';

function qs(params: ListParams & { view?: string; group?: string }) {
  const q = new URLSearchParams({ page: String(params.page), pageSize: String(params.pageSize) });
  if (params.search) q.set('search', params.search);
  if (params.sortBy) q.set('sortBy', params.sortBy);
  if (params.sortOrder) q.set('sortOrder', params.sortOrder);
  if (params.view) q.set('view', params.view);
  if (params.group) q.set('group', params.group);
  for (const [k, v] of Object.entries(params.filters ?? {})) v?.forEach((x) => q.append(k, x));
  return q.toString();
}

/** The `{ success, data }` transport every area client is built on; exported so one area can point at its own service. */
export function createTransport(baseUrl: string) {
  async function call<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetchWithIdentity(`${baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers as Record<string, string> | undefined) },
    });
    const body = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(body?.error?.message ?? res.statusText, res.status, body?.error?.team, body?.error?.code, body?.error?.details);
    return body?.data as T;
  }
  const get = <T>(p: string) => call<T>(p);
  const send = <T>(method: string, p: string, body?: unknown, headers?: Record<string, string>) => call<T>(p, { method, body: body ? JSON.stringify(body) : undefined, headers });
  return { get, send, qs };
}

/** Chat against its own service (the Runtime) while other areas use another client. */
export const createChatOnlyHttp = (baseUrl: string) => {
  const t = createTransport(baseUrl);
  return createChatHttp(t.get, t.send, t.qs, baseUrl);
};

type Get = ReturnType<typeof createTransport>['get'];
type Send = ReturnType<typeof createTransport>['send'];

function createReviewsHttp(get: Get, send: Send): OpsApi['reviews'] {
  return {
    list: (p) => get(`/reviews?${qs(p)}`),
    // Review ids hold colons (run:step:iteration); every path encodes them once, from the raw id.
    get: (id) => get(`/reviews/${encodeURIComponent(id)}`),
    byRunKey: (key) => get(`/reviews/by-run-key/${encodeURIComponent(key)}`),
    place: (id, opts) => get(`/reviews/${encodeURIComponent(id)}/place${opts ? `?${new URLSearchParams(Object.entries(opts).filter(([, v]) => v) as [string, string][]).toString()}` : ''}`),
    decide: (id, i) => send('POST', `/reviews/${encodeURIComponent(id)}/decision`, i),
    assign: (ids, assignee) => send('POST', '/reviews/assign', { ids, assignee }),
    bulkDecide: (ids, decision, reason, opts) => send('POST', '/reviews/bulk-decision', { ids, decision, reason, stepUpToken: opts?.stepUpToken }),
  };
}

/** Workflow runs (the Cases page) and Reviews against the agents service, which serves them from runtime threads. */
export function createCasesOnlyHttp(baseUrl: string): { runs: CasesApi['runs']; run: CasesApi['run']; runState: CasesApi['runState']; startRun: CasesApi['startRun']; startable: CasesApi['startable']; reviews: OpsApi['reviews'] } {
  const t = createTransport(baseUrl);
  const cases = createCasesHttp(t.get, t.send, t.qs);
  return { runs: cases.runs, run: cases.run, runState: cases.runState, startRun: cases.startRun, startable: cases.startable, reviews: createReviewsHttp(t.get, t.send) };
}

/**
 * Agents, Workflows and Skills against the agents-service registry under `/v1`. It has no bulk routes, so those are
 * left out. Skills: list, detail, create, drafts, publish requests, deprecate, delete, options and agent pins are
 * served; the rest (tests, resources, generation, import, export) answers 501 so a page says so instead of showing
 * mock data beside real skills.
 */
/** A tool as agents-service's directory lists it (`GET /v1/tools`): a published operation or workflow. */
interface DirectoryTool {
  id: string;
  name: string;
  server: string;
  moduleId: string | null;
  description: string;
  access: 'read' | 'write' | 'workflow';
  inputSchema: Record<string, unknown>;
  requiresApproval: boolean;
}

/**
 * Tools on the registry: the directory of what can be granted or called (published operations and workflows). It
 * lists only what is published, so every row is enabled, and it carries no call counts; the type and access filters go
 * to the server as `access`. Writing tools (create, update, test) has no route here: those stay on the mock and the
 * Tools page manages modules on tools-service instead.
 */
export function createRegistryToolsList(baseUrl: string): OpsApi['tools']['list'] {
  const { get } = createTransport(`${baseUrl}/v1`);
  return async (p) => {
    const wanted = [...(p.filters?.type?.includes('workflow') ? ['workflow'] : []), ...(p.filters?.access ?? [])];
    const rows = await get<DirectoryTool[]>(`/tools${wanted.length ? `?${new URLSearchParams(wanted.map((a) => ['access', a]))}` : ''}`);
    const data: Tool[] = rows.map((t) => ({
      id: t.id,
      name: t.name,
      description: t.description,
      type: t.access === 'workflow' ? 'workflow' : 'http',
      system: t.server,
      access: t.access === 'workflow' ? 'write' : t.access,
      requiresReview: t.requiresApproval,
      enabled: true,
      calls24h: 0,
      errorRate: 0,
      p95Ms: 0,
      grantedAgentIds: [],
      sampleInput: '',
      moduleId: t.moduleId ?? undefined,
      module: t.server,
    }));
    return {
      data,
      pagination: { page: 1, pageSize: data.length, total: data.length, totalPages: 1, hasNext: false, hasPrev: false },
      facets: {},
      stats: { total: data.length, disabled: 0, systems: 0, calls24h: 0, callsTrendPct: 0, busiest: '', requireReview: 0, noisy: [] },
    };
  };
}

export function createRegistryOnlyHttp(baseUrl: string): Pick<OpsApi, 'agents' | 'workflows' | 'engine' | 'channels' | 'skills' | 'guardrails' | 'widgets' | 'widgetDeployments' | 'forms' | 'batches' | 'caseRecords' | 'activity' | 'overview'> {
  const { agents, workflows, engine, channels, skills, guardrails, widgets, widgetDeployments, forms, batches, caseRecords, activity, overview } = createHttpApi(`${baseUrl}/v1`);
  const { bulkUpdate: _au, bulkRemove: _ar, ...agentCalls } = agents;
  const { bulkUpdate: _wu, ...workflowCalls } = workflows;
  const notServed = (what: string) => () => Promise.reject(new ApiError(`${what} is not available on this backend yet.`, 501));
  return {
    agents: agentCalls,
    workflows: workflowCalls,
    engine,
    channels,
    guardrails,
    widgets,
    widgetDeployments,
    forms,
    batches,
    caseRecords,
    activity,
    // Counted on the server from the same review list Human Tasks reads and the team's cases (c-129).
    overview,
    skills: {
      ...skills,
      restore: notServed('Restoring a skill version'),
      duplicate: notServed('Duplicating a skill'),
      bulkDeprecate: notServed('Bulk deprecate'),
      bulkRemove: notServed('Bulk delete'),
      exportSkills: notServed('Skill export'),
      tests: { add: notServed('Skill tests'), update: notServed('Skill tests'), remove: notServed('Skill tests'), run: notServed('Skill tests') },
      resources: { add: notServed('Skill resources'), remove: notServed('Skill resources') },
      // eslint-disable-next-line require-yield
      generate: async function* () {
        throw new ApiError('Skill generation is not available on this backend yet.', 501);
      },
      rewriteSection: notServed('Section rewrite'),
      suggestTests: notServed('Suggested tests'),
      dryRun: notServed('Dry runs'),
      impact: notServed('Impact checks'),
      generateOptions: notServed('Skill generation'),
      candidates: notServed('Skill candidates'),
      previewImport: notServed('Skill import'),
      importSkill: notServed('Skill import'),
    },
  };
}

/** Tool modules, the egress allow-list, secrets, connections and the gateway's call log (Activity) against tools-service under `/v1`. */
export function createToolsOnlyHttp(baseUrl: string): Pick<OpsApi, 'toolModules' | 'egress' | 'secrets' | 'connections'> & { toolCalls: GovernanceApi['toolCalls'] } {
  const t = createTransport(`${baseUrl}/v1`);
  return {
    toolModules: createToolModulesHttp(t.get, t.send, t.qs),
    egress: createEgressHttp(t.get, t.send, t.qs),
    secrets: createSecretsHttp(t.get, t.send, t.qs),
    connections: createConnectionsHttp(t.get, t.send),
    toolCalls: createExecutionsHttp(t.get),
  };
}

/** Knowledge bases, sources, documents and changes on kb-service, which serves the same routes under /v1. */
export function createKnowledgeOnlyHttp(baseUrl: string): Pick<OpsApi, 'knowledge' | 'knowledgeChanges'> {
  const t = createTransport(`${baseUrl}/v1`);
  return { knowledge: createKnowledgeHttp(t.get, t.send, t.qs), knowledgeChanges: createKnowledgeChangesHttp(t.get, t.send, t.qs) };
}

/** REST client for a real Ops AI backend; responses use the `{ success, data }` envelope. */
export function createHttpApi(baseUrl: string): OpsApi {
  const { get, send } = createTransport(baseUrl);

  return {
    overview: { get: () => get('/overview') },
    agents: {
      list: (p) => get(`/agents?${qs(p)}`),
      get: (id) => get(`/agents/${id}`),
      create: (i) => send('POST', '/agents', i),
      update: (id, i) => send('PATCH', `/agents/${id}`, i),
      remove: (id) => send('DELETE', `/agents/${id}`),
      versions: (id) => get(`/agents/${id}/versions`),
      runs: (id) => get(`/agents/${id}/runs`),
      restore: (id, version) => send('POST', `/agents/${id}/versions/${version}/restore`),
      requestPublish: (id, version, note) => send('POST', `/agents/${id}/publish-requests`, { version, note }),
      publishPreview: (id, version) => get(`/agents/${id}/publish-preview?version=${version}`),
      setPaused: (id, paused) => send('POST', `/agents/${id}/paused`, { paused }),
      grantableTools: () => get('/tools'),
      toolOptions: (p) => get(`/tools/options?${optionsQs(p)}`),
      modelAliases: () => get('/model-aliases'),
      bulkUpdate: (ids, patch) => send('POST', '/agents/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/agents/bulk-delete', { ids }),
    },
    workflows: {
      // The current engine's workflows only: the console no longer shows the earlier engine's (c-562).
      list: (p) => get(`/workflows?${qs(p)}&engine=current`),
      get: (id) => get(`/workflows/${id}`),
      create: (i) => send('POST', '/workflows', i),
      validate: (id, graph, target) => send('POST', `/workflows/${id}/validate`, { graph, target }),
      lastValidation: (id) => get(`/workflows/${id}/validations/latest`),
      test: (id, input) => send('POST', `/workflows/${id}/test`, input),
      routeFields: () => get('/workflows/route-fields'),
      saveDraft: (id, graph) => (graph ? send('PUT', `/workflows/${id}/draft`, { graph }) : send('DELETE', `/workflows/${id}/draft`)),
      requestPublish: (id, i) => send('POST', `/workflows/${id}/publish-requests`, i),
      update: (id, i) => send('PATCH', `/workflows/${id}`, i),
      setStatus: (id, status) => send('POST', `/workflows/${id}/status`, { status }),
      remove: (id) => send('DELETE', `/workflows/${id}`),
      runs: (id, p) => get(`/workflows/${id}/runs?${qs(p)}`),
      versions: (id) => get(`/workflows/${id}/versions`),
      restore: (id, version) => send('POST', `/workflows/${id}/versions/${version}/restore`),
      bulkUpdate: (ids, patch) => send('POST', '/workflows/bulk-update', { ids, patch }),
    },
    reviews: createReviewsHttp(get, send),
    policies: {
      list: (p) => get(`/gate-policies?${qs(p)}`),
      create: (i) => send('POST', '/gate-policies', i),
      update: (id, i) => send('PUT', `/gate-policies/${id}`, i),
      remove: (id) => send('DELETE', `/gate-policies/${id}`),
      bulkUpdate: (ids, patch) => send('POST', '/gate-policies/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/gate-policies/bulk-delete', { ids }),
    },
    knowledge: createKnowledgeHttp(get, send, qs),
    cases: createCasesHttp(get, send, qs),
    chat: createChatHttp(get, send, qs, baseUrl),
    knowledgeChanges: createKnowledgeChangesHttp(get, send, qs),
    search: createSearchHttp(get, send),
    notifications: createNotificationsHttp(get, send),
    governance: createGovernanceHttp(get, send, qs),
    settings: createSettingsHttp(get, send, qs),
    signInPolicy: createSignInPolicyHttp(get, send),
    invites: createInvitesHttp(get, send),
    account: createAccountHttp(get, send, qs),
    workspacePolicies: createWorkspacePoliciesHttp(get, send),
    workspaceTeams: createWorkspaceTeamsHttp(get, send),
    signInProviders: createSignInProvidersHttp(get, send),
    providerKeys: createProviderKeysHttp(get, send),
    evals: createEvalsHttp(get, send, qs),
    modelRisk: createModelRiskHttp(get, send, qs),
    toolModules: createToolModulesHttp(get, send, qs),
    egress: createEgressHttp(get, send, qs),
    secrets: createSecretsHttp(get, send, qs),
    connections: createConnectionsHttp(get, send),
    integrations: createIntegrationsHttp(get, send, qs),
    files: createFilesHttp(get, send, qs),
    engine: createEngineHttp(get, send),
    channels: createChannelsHttp(get, send),
    templates: createTemplatesHttp(get, send, qs),
    prompts: createPromptsHttp(get, send, qs, baseUrl),
    skills: createSkillsHttp(get, send, qs, baseUrl),
    widgets: createWidgetsHttp(get, send, qs),
    widgetDeployments: createWidgetDeploymentsHttp(get, send, baseUrl),
    forms: createFormsHttp(get, send),
    batches: createBatchesHttp(get, send, baseUrl),
    caseRecords: createCaseRecordsHttp(get, send),
    activity: createActivityHttp(get),
    guardrails: createGuardrailsHttp(get, send, qs),
    assurance: createAssuranceHttp(get, send, qs),
    connect: createConnectHttp(get, send),
    wiki: createWikiHttp(get, send, qs),
    tools: {
      list: (p) => get(`/tools?${qs(p)}`),
      create: (i) => send('POST', '/tools', i),
      update: (id, i) => send('PATCH', `/tools/${id}`, i),
      remove: (id) => send('DELETE', `/tools/${id}`),
      test: (id, input) => send('POST', `/tools/${id}/test`, { input }),
      bulkUpdate: (ids, patch) => send('POST', '/tools/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/tools/bulk-delete', { ids }),
    },
    deployments: {
      list: (p) => get(`/deployments?${qs(p)}`),
      create: (i) => send('POST', '/deployments', i),
      update: (id, p) => send('PATCH', `/deployments/${id}`, p),
      remove: (id) => send('DELETE', `/deployments/${id}`),
      rotateKey: (id) => send('POST', `/deployments/${id}/rotate-key`),
      promote: (id, i) => send('POST', `/deployments/${id}/promote`, i),
      bulkUpdate: (ids, patch) => send('POST', '/deployments/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/deployments/bulk-delete', { ids }),
    },
    tests: {
      list: (wid) => get(`/workflows/${wid}/tests`),
      create: (wid, i) => send('POST', `/workflows/${wid}/tests`, i),
      importRows: (wid, rows, fileId) => send('POST', `/workflows/${wid}/tests/import`, { rows, fileId }),
      fromRun: (runId) => send('POST', `/runs/${runId}/test-case`),
      remove: (id) => send('DELETE', `/tests/${id}`),
    },
    lookups: { get: () => get('/lookups') },
    teams: { list: () => get('/teams'), create: (i) => send('POST', '/teams', i) },
  };
}
