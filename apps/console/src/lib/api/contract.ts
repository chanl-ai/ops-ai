import type { CasesApi } from './cases-contract';
import type { ChatApi } from './chat-contract';
import type { KnowledgeApi } from './knowledge-contract';
import type { KnowledgeChangesApi } from './knowledge-changes-contract';
import type { NotificationsApi } from './notifications-contract';
import type { RunAsApi } from './run-as-contract';
import type { SearchApi } from './search-contract';
import type { GovernanceApi } from './governance-contract';
import type { SettingsApi } from './settings-contract';
import type { SignInPolicyApi } from './sign-in-contract';
import type { InvitesApi } from './invites-contract';
import type { AccountApi } from './account-contract';
import type { EvalsApi } from './evals-contract';
import type { ModelRiskApi } from './model-risk-contract';
import type { ToolModulesApi } from './tool-modules-contract';
import type { EgressApi } from './egress-contract';
import type { SecretsApi } from './secrets-contract';
import type { IntegrationsApi } from './integrations-contract';
import type { FilesApi } from './files-contract';
import type { TemplatesApi } from './templates-contract';
import type { PromptsApi } from './prompts-contract';
import type { SkillsApi } from './skills-contract';
import type { AssuranceApi } from './assurance-contract';
import type { ConnectApi } from './connect-contract';
import type { WikiApi } from './wiki-contract';
import type {
  Agent,
  AgentInput,
  AgentVersion,
  AgentPatch,
  AgentTestTurn,
  BulkResult,
  Deployment,
  DeploymentInput,
  DeploymentPatch,
  TestCase,
  TestCaseInput,
  ValidationRun,
  LifecycleStatus,
  ReviewDecision,
  Version,
  WorkflowRun,
  WorkflowSettingsInput,
  GatePolicy,
  GatePolicyInput,
  Overview,
  Review,
  ReviewDecisionInput,
  Tool,
  ToolInput,
  ToolTestResult,
  Workflow,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowTestRun,
  GrantableTool,
  ModelAlias,
  RouteFields,
  WorkflowInput,
} from '@/lib/types/domain';
import type {
  AgentFilters,
  DeploymentFilters,
  ListParams,
  ListResult,
  PolicyFilters,
  ReviewListParams,
  RunFilters,
  ReviewStats,
  ReviewViewCounts,
  ToolFilters,
  ToolStats,
  WorkflowFilters,
} from '@/lib/types/query';
import type { Team, TeamInput, TeamRef } from '@/lib/types/team';

/**
 * Everything the UI may ask of the backend. Pages reach it only through hooks/, and the
 * implementation is chosen in lib/api/index.ts, so swapping mock for HTTP touches one file.
 */
export interface OpsApi {
  overview: {
    get(): Promise<Overview>;
  };
  agents: {
    list(params: ListParams<AgentFilters>): Promise<ListResult<Agent>>;
    get(id: string): Promise<Agent>;
    create(input: AgentInput): Promise<Agent>;
    /** Saves a new draft version. Workflows keep pinning the published one until it is published and they republish. */
    update(id: string, patch: AgentPatch): Promise<Agent>;
    remove(id: string): Promise<void>;
    versions(id: string): Promise<AgentVersion[]>;
    /** Copies a version into a new draft; nothing publishes. */
    restore(id: string, version: number): Promise<Agent>;
    /**
     * Sends a draft version to Reviews as an `agent_publish` review. 409 when one is already open for the agent;
     * 422 when the version is not the newest draft. Approving it, by someone other than the requester and the
     * author, publishes the version (spec 04 5.11).
     */
    requestPublish(id: string, version: number, note: string): Promise<Review>;
    /** Pauses or resumes the agent for new runs. 409 when pausing an agent that has never been published. */
    setPaused(id: string, paused: boolean): Promise<Agent>;
    /** `runAsId` answers with that staff member's or role's permissions (see run-as-contract.ts). */
    test(id: string, message: string, runAsId?: string): Promise<AgentTestTurn>;
    /** The tools any agent may be granted; a grant names their ids, and an unknown id is refused. */
    grantableTools(): Promise<GrantableTool[]>;
    /** The model aliases an agent may name; a publish naming any other is refused (422 unknown_model_alias). */
    modelAliases(): Promise<ModelAlias[]>;
    /** Absent when the backend has no bulk route (the agents-service registry); the list then offers no bulk actions. */
    bulkUpdate?(ids: string[], patch: { paused?: boolean; owner?: string }): Promise<BulkResult>;
    bulkRemove?(ids: string[]): Promise<BulkResult>;
  };
  workflows: {
    list(params: ListParams<WorkflowFilters>): Promise<ListResult<Workflow>>;
    get(id: string): Promise<WorkflowDetail>;
    create(input: WorkflowInput): Promise<Workflow>;
    /** Runs the workflow's test cases against a draft graph (and the live version for comparison). Advisory: never blocks. */
    validate(id: string, graph: WorkflowGraph, target?: 'draft' | 'live'): Promise<ValidationRun>;
    lastValidation(id: string): Promise<ValidationRun | null>;
    /** Runs a graph (the draft when left out) once on a sample case; each pause is approved so the run reaches its end. */
    test(id: string, input: { graph?: WorkflowGraph }): Promise<WorkflowTestRun>;
    /** The fields and operators a branch's routes may compare; publishing refuses anything else. */
    routeFields(): Promise<RouteFields>;
    /** Saves the canvas draft; `null` discards it. */
    saveDraft(id: string, graph: WorkflowGraph | null): Promise<WorkflowDetail['draft'] | null>;
    /** Sends a draft to the Reviews queue as a publish request; approving it there publishes. */
    requestPublish(id: string, input: { graph: WorkflowGraph; note: string; validationRunId?: string; checksFailing: number }): Promise<Review>;
    update(id: string, input: WorkflowSettingsInput): Promise<Workflow>;
    setStatus(id: string, status: LifecycleStatus): Promise<Workflow>;
    remove(id: string): Promise<void>;
    runs(id: string, params: ListParams<RunFilters>): Promise<ListResult<WorkflowRun>>;
    versions(id: string): Promise<Version[]>;
    restore(id: string, version: number): Promise<Workflow>;
    /** Absent when the backend has no bulk route (the agents-service registry). */
    bulkUpdate?(ids: string[], patch: { status?: LifecycleStatus; owner?: string }): Promise<BulkResult>;
  };
  reviews: {
    list(params: ReviewListParams): Promise<ListResult<Review> & { viewCounts: ReviewViewCounts; stats: ReviewStats }>;
    get(id: string): Promise<Review>;
    decide(id: string, input: ReviewDecisionInput): Promise<Review>;
    assign(ids: string[], assignee?: string): Promise<BulkResult>;
    /** Approving calls that need two approvers needs `stepUpToken` from a re-authentication in the last 5 minutes; one covers the batch. */
    bulkDecide(ids: string[], decision: ReviewDecision, reason?: string, opts?: { stepUpToken?: string }): Promise<BulkResult>;
  };
  policies: {
    list(params: ListParams<PolicyFilters>): Promise<ListResult<GatePolicy>>;
    create(input: GatePolicyInput): Promise<GatePolicy>;
    update(id: string, input: GatePolicyInput): Promise<GatePolicy>;
    remove(id: string): Promise<void>;
    bulkUpdate(ids: string[], patch: { sla?: string; reviewers?: string }): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  knowledge: KnowledgeApi;
  knowledgeChanges: KnowledgeChangesApi;
  search: SearchApi;
  notifications: NotificationsApi;
  runAs: RunAsApi;
  cases: CasesApi;
  chat: ChatApi;
  governance: GovernanceApi;
  settings: SettingsApi;
  signInPolicy: SignInPolicyApi;
  invites: InvitesApi;
  account: AccountApi;
  evals: EvalsApi;
  modelRisk: ModelRiskApi;
  toolModules: ToolModulesApi;
  /** The tenant's egress allow-list (tools-service). */
  egress: EgressApi;
  /** Credentials tool calls send; values never come back (tools-service). */
  secrets: SecretsApi;
  integrations: IntegrationsApi;
  files: FilesApi;
  templates: TemplatesApi;
  prompts: PromptsApi;
  skills: SkillsApi;
  assurance: AssuranceApi;
  connect: ConnectApi;
  wiki: WikiApi;
  tools: {
    list(params: ListParams<ToolFilters>): Promise<ListResult<Tool> & { stats: ToolStats }>;
    create(input: ToolInput): Promise<Tool>;
    update(id: string, input: Partial<ToolInput> & { enabled?: boolean }): Promise<Tool>;
    remove(id: string): Promise<void>;
    test(id: string, input: string): Promise<ToolTestResult>;
    bulkUpdate(ids: string[], patch: { enabled?: boolean; requiresReview?: boolean }): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  /** Option lists for selects (owners, reviewer groups, models, collections, systems). */
  deployments: {
    list(params: ListParams<DeploymentFilters>): Promise<ListResult<Deployment>>;
    create(input: DeploymentInput): Promise<Deployment>;
    update(id: string, patch: DeploymentPatch): Promise<Deployment>;
    remove(id: string): Promise<void>;
    /** Issues a new API key; the full key is returned once and never again. */
    rotateKey(id: string): Promise<{ key: string; deployment: Deployment }>;
    /** Copies a staging deployment into a new production deployment; the staging one keeps running. */
    promote(id: string, input: { name: string; allowedDomains?: string[] }): Promise<Deployment>;
    bulkUpdate(ids: string[], patch: { status?: Deployment['status']; toLatest?: boolean }): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  tests: {
    list(workflowId: string): Promise<TestCase[]>;
    create(workflowId: string, input: TestCaseInput): Promise<TestCase>;
    /** `fileId` is the uploaded CSV the rows came from; the test set is recorded as one of its references. */
    importRows(workflowId: string, rows: TestCaseInput[], fileId?: string): Promise<BulkResult>;
    fromRun(runId: string): Promise<TestCase>;
    remove(id: string): Promise<void>;
  };
  lookups: {
    get(): Promise<Lookups>;
  };
  /** Teams the user can switch between. The current team id is sent with every call (see team-context.ts). */
  teams: {
    list(): Promise<Team[]>;
    /** Absent under platform sign-in, where an admin creates teams in platform settings; the switcher then offers no Add team. */
    create?(input: TeamInput): Promise<Team>;
  };
}

export interface Lookups {
  owners: string[];
  models: string[];
  reviewerGroups: string[];
  /** People who can be assigned a review. */
  reviewers: string[];
  slaOptions: string[];
  collections: string[];
  systems: string[];
  workflows: { id: string; name: string }[];
  currentUser: { name: string; email: string };
  workspace: { name: string; environment: string };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Set on a 403 for a record that belongs to another team, so the page can offer to switch. */
    readonly team?: TeamRef,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
