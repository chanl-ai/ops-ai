import type { ListParams } from '@/lib/types/query';

import { ApiError, type OpsApi } from './contract';
import type { CasesApi } from './cases-contract';
import { createCasesHttp } from './cases-http';
import { createChatHttp } from './chat-http';
import { createKnowledgeHttp } from './knowledge-http';
import { createKnowledgeChangesHttp } from './knowledge-changes-http';
import { createNotificationsHttp } from './notifications-http';
import { createRunAsHttp } from './run-as-http';
import { createSearchHttp } from './search-http';
import { createGovernanceHttp } from './governance-http';
import { createSettingsHttp } from './settings-http';
import { createSignInPolicyHttp } from './sign-in-http';
import { createInvitesHttp } from './invites-http';
import { createAccountHttp } from './account-http';
import { createEvalsHttp } from './evals-http';
import { createModelRiskHttp } from './model-risk-http';
import { createToolModulesHttp } from './tool-modules-http';
import { createEgressHttp } from './egress-http';
import { createSecretsHttp } from './secrets-http';
import { createIntegrationsHttp } from './integrations-http';
import { createFilesHttp } from './files-http';
import { createTemplatesHttp } from './templates-http';
import { createPromptsHttp } from './prompts-http';
import { createSkillsHttp } from './skills-http';
import { createAssuranceHttp } from './assurance-http';
import { createConnectHttp } from './connect-http';
import { createWikiHttp } from './wiki-http';
import { fetchWithIdentity } from './request-identity';

function qs(params: ListParams & { view?: string }) {
  const q = new URLSearchParams({ page: String(params.page), pageSize: String(params.pageSize) });
  if (params.search) q.set('search', params.search);
  if (params.sortBy) q.set('sortBy', params.sortBy);
  if (params.sortOrder) q.set('sortOrder', params.sortOrder);
  if (params.view) q.set('view', params.view);
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
    if (!res.ok) throw new ApiError(body?.error?.message ?? res.statusText, res.status, body?.error?.team);
    return body?.data as T;
  }
  const get = <T>(p: string) => call<T>(p);
  const send = <T>(method: string, p: string, body?: unknown) => call<T>(p, { method, body: body ? JSON.stringify(body) : undefined });
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
    get: (id) => get(`/reviews/${id}`),
    decide: (id, i) => send('POST', `/reviews/${id}/decision`, i),
    assign: (ids, assignee) => send('POST', '/reviews/assign', { ids, assignee }),
    bulkDecide: (ids, decision, reason, opts) => send('POST', '/reviews/bulk-decision', { ids, decision, reason, stepUpToken: opts?.stepUpToken }),
  };
}

/** Workflow runs (the Cases page) and Reviews against the agents service, which serves them from runtime threads. */
export function createCasesOnlyHttp(baseUrl: string): { runs: CasesApi['runs']; run: CasesApi['run']; startRun: CasesApi['startRun']; startable: CasesApi['startable']; reviews: OpsApi['reviews'] } {
  const t = createTransport(baseUrl);
  const cases = createCasesHttp(t.get, t.send, t.qs);
  return { runs: cases.runs, run: cases.run, startRun: cases.startRun, startable: cases.startable, reviews: createReviewsHttp(t.get, t.send) };
}

/** Agents and Workflows against the agents-service registry under `/v1`. It has no bulk routes, so those are left out. */
export function createRegistryOnlyHttp(baseUrl: string): Pick<OpsApi, 'agents' | 'workflows'> {
  const { agents, workflows } = createHttpApi(`${baseUrl}/v1`);
  const { bulkUpdate: _au, bulkRemove: _ar, ...agentCalls } = agents;
  const { bulkUpdate: _wu, ...workflowCalls } = workflows;
  return { agents: agentCalls, workflows: workflowCalls };
}

/** Tool modules, the egress allow-list and secrets against tools-service under `/v1`. */
export function createToolsOnlyHttp(baseUrl: string): Pick<OpsApi, 'toolModules' | 'egress' | 'secrets'> {
  const t = createTransport(`${baseUrl}/v1`);
  return { toolModules: createToolModulesHttp(t.get, t.send, t.qs), egress: createEgressHttp(t.get, t.send), secrets: createSecretsHttp(t.get, t.send) };
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
      restore: (id, version) => send('POST', `/agents/${id}/versions/${version}/restore`),
      requestPublish: (id, version, note) => send('POST', `/agents/${id}/publish-requests`, { version, note }),
      setPaused: (id, paused) => send('POST', `/agents/${id}/paused`, { paused }),
      test: (id, message, runAsId) => send('POST', `/agents/${id}/test`, { message, runAsId }),
      grantableTools: () => get('/tools'),
      modelAliases: () => get('/model-aliases'),
      bulkUpdate: (ids, patch) => send('POST', '/agents/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/agents/bulk-delete', { ids }),
    },
    workflows: {
      list: (p) => get(`/workflows?${qs(p)}`),
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
    runAs: createRunAsHttp(get),
    governance: createGovernanceHttp(get, send, qs),
    settings: createSettingsHttp(get, send, qs),
    signInPolicy: createSignInPolicyHttp(get, send),
    invites: createInvitesHttp(get, send),
    account: createAccountHttp(get, send, qs),
    evals: createEvalsHttp(get, send, qs),
    modelRisk: createModelRiskHttp(get, send, qs),
    toolModules: createToolModulesHttp(get, send, qs),
    egress: createEgressHttp(get, send),
    secrets: createSecretsHttp(get, send),
    integrations: createIntegrationsHttp(get, send, qs),
    files: createFilesHttp(get, send, qs),
    templates: createTemplatesHttp(get, send, qs),
    prompts: createPromptsHttp(get, send, qs, baseUrl),
    skills: createSkillsHttp(get, send, qs, baseUrl),
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
