import type { CasesApi } from './cases-contract';
import type { ChatApi } from './chat-contract';
import type { KnowledgeApi } from './knowledge-contract';
import type { KnowledgeChangesApi } from './knowledge-changes-contract';
import type { NotificationsApi } from './notifications-contract';
import type { RunAsApi } from './run-as-contract';
import type { SearchApi } from './search-contract';
import type { GovernanceApi } from './governance-contract';
import type { SettingsApi } from './settings-contract';
import type { EvalsApi } from './evals-contract';
import type { ModelRiskApi } from './model-risk-contract';
import type { ToolModulesApi } from './tool-modules-contract';
import type {
  Agent,
  AgentInput,
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
    update(id: string, patch: AgentPatch): Promise<Agent>;
    remove(id: string): Promise<void>;
    versions(id: string): Promise<Version[]>;
    restore(id: string, version: number): Promise<Agent>;
    setStatus(id: string, status: LifecycleStatus): Promise<Agent>;
    /** `runAsId` answers with that staff member's or role's permissions (see run-as-contract.ts). */
    test(id: string, message: string, runAsId?: string): Promise<AgentTestTurn>;
    bulkUpdate(ids: string[], patch: { status?: LifecycleStatus; owner?: string }): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  workflows: {
    list(params: ListParams<WorkflowFilters>): Promise<ListResult<Workflow>>;
    get(id: string): Promise<WorkflowDetail>;
    create(input: WorkflowInput): Promise<Workflow>;
    /** Runs the workflow's test cases against a draft graph (and the live version for comparison). Advisory: never blocks. */
    validate(id: string, graph: WorkflowGraph, target?: 'draft' | 'live'): Promise<ValidationRun>;
    lastValidation(id: string): Promise<ValidationRun | null>;
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
    bulkUpdate(ids: string[], patch: { status?: LifecycleStatus; owner?: string }): Promise<BulkResult>;
  };
  reviews: {
    list(params: ReviewListParams): Promise<ListResult<Review> & { viewCounts: ReviewViewCounts; stats: ReviewStats }>;
    get(id: string): Promise<Review>;
    decide(id: string, input: ReviewDecisionInput): Promise<Review>;
    assign(ids: string[], assignee?: string): Promise<BulkResult>;
    bulkDecide(ids: string[], decision: ReviewDecision, reason?: string): Promise<BulkResult>;
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
  evals: EvalsApi;
  modelRisk: ModelRiskApi;
  toolModules: ToolModulesApi;
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
    importRows(workflowId: string, rows: TestCaseInput[]): Promise<BulkResult>;
    fromRun(runId: string): Promise<TestCase>;
    remove(id: string): Promise<void>;
  };
  lookups: {
    get(): Promise<Lookups>;
  };
  /** Teams the user can switch between. The current team id is sent with every call (see team-context.ts). */
  teams: {
    list(): Promise<Team[]>;
    create(input: TeamInput): Promise<Team>;
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
