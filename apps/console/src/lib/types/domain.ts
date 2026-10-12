import type { EmailWorkflowConfig } from './cases';

export type Risk = 'critical' | 'high' | 'medium' | 'low';
export type ReviewStatus = 'pending' | 'in_review' | 'approved' | 'rejected' | 'returned';
export type ReviewKind = 'approval' | 'exception' | 'escalation' | 'policy_override' | 'publish_request' | 'agent_publish' | 'model_validation' | 'skill_publish' | 'template_submission';
export type ReviewDecision = 'approved' | 'rejected' | 'returned';
export type LifecycleStatus = 'live' | 'draft' | 'paused';
export type Channel = 'voice' | 'chat' | 'email' | 'api';
export type ToolAccess = 'read' | 'write' | 'money_movement';
/** `workflow`: a published workflow exposed to agents; calling it starts a run of that workflow. */
export type ToolType = 'http' | 'code' | 'mcp' | 'workflow';

/** How a workflow behaves when it is called as a tool, from its approval rules. */
export type WorkflowToolApproval = 'pauses_on_writes' | 'pauses_always' | 'runs_without_pause';

export interface Agent {
  id: string;
  name: string;
  slug: string;
  role: string;
  instructions: string;
  model: string;
  channels: Channel[];
  toolIds: string[];
  collections: string[];
  owner: string;
  /**
   * Operator switch: new runs stop using the agent while it is paused. Independent of versions; pins and pending
   * publishes are unchanged.
   */
  paused: boolean;
  /** Computed by the API: `paused` when paused, else `published` once a version is published, else `not_published`. */
  availability: AgentAvailability;
  /** Newest saved version, draft or published. */
  version: number;
  /** The version workflows may pin; null until the first `agent_publish` review is approved (spec 01 4.5). */
  publishedVersion: number | null;
  updatedAt: string;
  tasks24h: number;
  autoResolvedRate: number;
  workflowIds: string[];
  guardrails: AgentGuardrails;
  /** The agent's wrapper workflow, once it has been published (see `Workflow.wrapsAgentId`). */
  wrapperWorkflowId?: string;
  /** Workflows that use this agent, with the agent version each one was published with. */
  usedIn: { workflowId: string; workflowName: string; pinnedVersion: number; status: LifecycleStatus }[];
}

export interface AgentGuardrails {
  redactPii: boolean;
  maxToolCallsPerTurn: number;
  whenUnsure: 'handoff' | 'ask' | 'decline';
  blockedTopics: string[];
}

/** One save of the agent page; every save becomes a new agent version. */
export type AgentPatch = Partial<AgentInput> & { toolIds?: string[]; collections?: string[]; guardrails?: AgentGuardrails; note?: string };

export interface AgentInput {
  name: string;
  role: string;
  model: string;
  owner: string;
  channels: Channel[];
  instructions?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  owner: string;
  trigger: string;
  agentSlugs: string[];
  stepCount: number;
  gateCount: number;
  runs24h: number;
  reviewed24h: number;
  openReviews: number;
  status: LifecycleStatus;
  version: number;
  updatedAt: string;
  /** Set while a publish request for this workflow waits in the Reviews queue. */
  pendingPublish?: { reviewId: string; toVersion: number; requestedBy: string };
  deploymentCount: number;
  /** Email intake workflows are configured with forms (intents, routing, approvals) instead of the canvas. */
  kind?: 'standard' | 'email_intake';
  /**
   * Set on an agent's wrapper: the one-step "Chat message → Agent → Reply" workflow an agent deploys through.
   * Created by the platform the first time the agent is published; its publish follows the agent's.
   */
  wrapsAgentId?: string;
  /** The wrapped agent's name, filled by the API. */
  wrapsAgentName?: string;
}

export interface WorkflowInput {
  name: string;
  trigger: string;
  template: 'blank' | 'approval' | 'triage' | 'chat';
  /** For the chat template: the agent the workflow wraps. */
  agentSlug?: string;
}

export type WorkflowSettingsInput = Pick<Workflow, 'name' | 'description' | 'owner' | 'trigger'>;

/** Graph node payload; mirrors the ReactFlow node data the editor renders. */
export interface WorkflowNodeData {
  label: string;
  description: string;
  icon: string;
  category: string;
  badge?: string;
  reviewers?: string;
  condition?: string;
  sla?: string;
  fourEyes?: boolean;
  [key: string]: unknown;
}

export interface WorkflowGraph {
  workflowId: string;
  nodes: { id: string; type: string; position: { x: number; y: number }; data: WorkflowNodeData }[];
  edges: { id: string; source: string; target: string; sourceHandle?: string | null; label?: string; type?: string; style?: Record<string, string> }[];
  /** Email intake configuration; drafted, tested and published with the graph. */
  emailConfig?: EmailWorkflowConfig;
}

/** A tool an agent may be granted, from the runtime's catalogue (GET /v1/tools); `id` is the tool name. */
export interface GrantableTool {
  id: string;
  name: string;
  /** The server or module the tool belongs to. */
  server: string;
  description: string;
  access: ToolAccess;
  /** The approval a call waits for, named; null when calls run without one. */
  approval: string | null;
}

/**
 * A chat model alias an agent may name (GET /v1/model-aliases): exactly the set publish accepts. Only `name` is
 * always present; the rest come from models-service and are absent when the runtime falls back to its own alias.
 */
export interface ModelAlias {
  name: string;
  kind: 'chat';
  clearedSensitivity?: string;
  inputPerMillion?: string;
  outputPerMillion?: string;
}

/** What a branch's route may compare: run fields with their type, and the operators each type allows. */
export interface RouteFields {
  fields: { name: string; type: 'text' | 'number' | 'boolean' }[];
  /** `list` operators take several values (one of). */
  ops: { op: string; label: string; types: RouteFields['fields'][number]['type'][]; list?: boolean }[];
}

/** One route of a branch: the comparison that sends a run down that path. */
export interface RouteWhen {
  field: string;
  op: string;
  value: string | number | boolean | (string | number)[];
}

/** One test run of a draft graph on a sample case: nothing is kept, and each pause is answered with an approval. */
export interface WorkflowTestRun {
  /** `stopped` when the run still waited after the allowed number of approvals, which means it loops. */
  status: 'completed' | 'stopped';
  pausesApproved: number;
  /** Node ids in the order the run reached them. */
  visited: string[];
  output?: string | null;
  endStatus?: string | null;
}

export interface WorkflowDetail extends Workflow {
  /** The published (live) graph. */
  graph: WorkflowGraph;
  /** Unpublished edits, saved as they are made. Survives navigation; cleared on discard or when its publish is approved. */
  draft?: { graph: WorkflowGraph; savedAt: string; savedBy: string };
}

export interface Evidence {
  kind: 'tool' | 'source';
  label: string;
  detail: string;
}

export interface Review {
  id: string;
  title: string;
  customer: string;
  workflowId: string;
  workflowName: string;
  agentSlug: string;
  /** Display name of the agent behind `agentSlug`, filled by the API. */
  agentName?: string;
  kind: ReviewKind;
  risk: Risk;
  confidence: number;
  proposal: string;
  actionTool: string;
  amount?: number;
  currency: string;
  policy: Pick<GatePolicy, 'id' | 'name' | 'condition' | 'reviewers' | 'sla' | 'onTimeout' | 'fourEyes'>;
  /** Minutes until the SLA lapses; negative once overdue. */
  slaMinutes: number;
  assignee?: string;
  approvals: string[];
  status: ReviewStatus;
  createdAt: string;
  decidedAt?: string;
  decisionReason?: string;
  reasoning: string[];
  evidence: Evidence[];
  /** Present on publish requests: what would ship and how it tested. */
  publish?: PublishRequestInfo;
  /** True when approving runs a money-movement operation; the console asks for a step-up first. Set by the API. */
  movesMoney?: boolean;
  /** Present on model validation reviews (second-line approval by Model Risk). */
  modelValidation?: import('./model-risk').ModelValidationRequest;
  /** Present on skill publish requests (spec 11). */
  skillPublish?: import('./skills').SkillPublishRequest;
  /** Present on template submissions (spec 12). */
  templateSubmission?: import('./templates').TemplateSubmissionRequest;
  /** Present on agent publish requests (spec 01 4.5, spec 04 5.11). */
  agentPublish?: AgentPublishRequest;
  /** The asset whose suite a rejected or returned decision can add a draft test case to; filled by the API. */
  testTarget?: import('./assurance').AssetRef;
}

export interface PublishRequestInfo {
  workflowId: string;
  fromVersion: number;
  toVersion: number;
  note: string;
  requestedBy: string;
  changes: string[];
  validation: ValidationSummary | null;
  /** Each pinned agent's eval result for the version being pinned, and the eval gate for the workflow's tier. */
  agentEvals?: import('./evals').AgentEvalPin[];
  evalGate?: import('./evals').EvalGate;
  modelEntry?: import('./model-risk').PublishModelEntry;
}

export interface ReviewDecisionInput {
  decision: ReviewDecision;
  reason?: string;
  /** Model validation only: conditions attached to an approval, and who is deciding (a run-as principal; unset is you). */
  conditions?: import('./model-risk').ConditionInput[];
  actingAsId?: string;
  /** Reject or return only: propose the reviewed input as a draft case in `testTarget`'s suite. */
  addTestCase?: boolean;
  /** Approving a money movement: the AuthProvider's step-up token from a re-authentication in the last 5 minutes. */
  stepUpToken?: string;
}

export interface GatePolicy {
  id: string;
  name: string;
  workflowId: string;
  workflowName: string;
  condition: string;
  reviewers: string;
  sla: string;
  onTimeout: string;
  fourEyes: boolean;
  hits7d: number;
}

export type GatePolicyInput = Pick<GatePolicy, 'name' | 'workflowId' | 'condition' | 'reviewers' | 'sla' | 'onTimeout' | 'fourEyes'>;

export interface Tool {
  id: string;
  name: string;
  description: string;
  type: ToolType;
  system: string;
  access: ToolAccess;
  requiresReview: boolean;
  enabled: boolean;
  calls24h: number;
  errorRate: number;
  p95Ms: number;
  grantedAgentIds: string[];
  sampleInput: string;
  /** The module this operation belongs to (spec 03 §4.1); set for every tool behind the data gateway. */
  moduleId?: string;
  module?: string;
  /** Set when `type` is `workflow`: the workflow it starts, its risk tier and whether it pauses for a person. */
  workflow?: { workflowId: string; tier: Risk; approval: WorkflowToolApproval; movesMoney: boolean };
}

export interface ToolInput {
  name: string;
  description: string;
  type: ToolType;
  system: string;
  access: ToolAccess;
  requiresReview: boolean;
}

export interface ToolTestResult {
  ok: boolean;
  status: number;
  tookMs: number;
  output: string;
}

export interface Overview {
  openReviews: number;
  overdueReviews: number;
  tasks24h: number;
  tasksTrendPct: number;
  autoResolvedRate: number;
  liveAgents: number;
  liveWorkflows: number;
  draftWorkflows: number;
  throughput7d: { day: string; completedByAgent: number; sentToReview: number }[];
  urgentReviews: Review[];
  workflowHealth: Workflow[];
  cases?: { open: number; breaching: number; awaitingApproval: number };
}

export interface Stat<T extends string = string> {
  key: T;
  label: string;
  value: number;
}

/** Facet counts returned with a list so filters can show how many rows each option matches. */
export type FacetCounts = Record<string, Record<string, number>>;

/** Outcome of a bulk call. Items the server refused are listed with the reason, never silently dropped. */
export interface BulkResult {
  updated: string[];
  skipped: { id: string; reason: string }[];
}

export interface Version {
  version: number;
  publishedAt: string;
  publishedBy: string;
  note: string;
  changes: string[];
  current: boolean;
  /** Agents: the eval result for this version, when one has run. */
  evalSummary?: import('./evals').EvalVersionSummary;
}

/** Whether workflows can pin an agent and new runs may use it (spec 01 4.5). */
export type AgentAvailability = 'published' | 'not_published' | 'paused';

export type AgentVersionState = 'draft' | 'in_review' | 'published' | 'superseded' | 'rejected';

/**
 * An agent version. Every save creates a draft; an `agent_publish` review publishes it (spec 01 4.5, spec 04
 * 5.11). `savedAt`/`savedBy` are the save; `publishedAt`/`publishedBy` are set once it is published.
 */
export interface AgentVersion extends Omit<Version, 'publishedAt' | 'publishedBy'> {
  state: AgentVersionState;
  savedAt: string;
  savedBy: string;
  publishedAt?: string;
  publishedBy?: string;
  /** The `agent_publish` review that published, rejected or is deciding this version. */
  reviewId?: string;
  /** Reason given when the review rejected or returned it. */
  decisionReason?: string;
}

/** Body of an `agent_publish` review: the version, its eval result against the published one, and who may approve. */
export interface AgentPublishRequest {
  agentId: string;
  agentName: string;
  version: number;
  /** The published version it replaces; null on first publish. */
  fromVersion: number | null;
  note: string;
  requestedBy: string;
  /** Whoever saved the version; maker-checker bars them from approving as well. */
  savedBy: string;
  tier: Risk;
  /** Why the tier is what it is: the live workflows that pin the agent, or its grants. */
  tierReason: string;
  approvalsNeeded: 1 | 2;
  candidate: import('./evals').EvalVersionSummary | null;
  published: import('./evals').EvalVersionSummary | null;
  /** Failing non-injection cases on the candidate; advisory at `low`, blocking above (spec 04 5.10.6 AG5). */
  failing: number;
  blockers: string[];
}

export type RunStatus = 'completed' | 'waiting_review' | 'failed' | 'running';
export type RunStepStatus = 'done' | 'waiting' | 'failed' | 'skipped';

export interface RunStep {
  nodeId: string;
  label: string;
  kind: 'trigger' | 'agent' | 'tool' | 'review' | 'action' | 'end';
  status: RunStepStatus;
  durationMs: number;
  detail?: string;
}

export interface WorkflowRun {
  id: string;
  workflowId: string;
  version: number;
  subject: string;
  status: RunStatus;
  startedAt: string;
  durationMs: number;
  reviewId?: string;
  error?: string;
  /** What started the run when it was not the workflow's own trigger, e.g. "Started by agent Branch Concierge". */
  trigger?: string;
  steps: RunStep[];
}


export interface AgentTestTurn {
  reply: string;
  toolCalls: { name: string; input: string; output: string }[];
  citations: { source: string; section: string }[];
  /** Set when, in production, this turn would pause at a review gate instead of acting. */
  wouldPause?: { gate: string; reviewers: string };
  tookMs: number;
  /** Present when the test ran as a staff member or role: what their permissions hid or blocked. */
  permissions?: import('./run-as').PermissionScope;
  /** Skills the runtime loaded for this turn, with the version the agent pins. */
  skills?: import('./skills').LoadedSkill[];
  /** Runs this turn started by calling workflow tools; each is a real run of that workflow. */
  startedRuns?: { runId: string; workflowId: string; workflowName: string; status: RunStatus }[];
}

// ── Deployments ──

/**
 * `mcp` exposes a published workflow as a tool on the workspace MCP URL, created from the Deployments MCP tab.
 * `chat` is console chat: every published agent has one on its wrapper workflow, created by the platform.
 */
export type DeployChannel = 'widget' | 'api' | 'email' | 'mcp' | 'chat';
export type DeployEnvironment = 'staging' | 'production';

export interface WidgetConfig {
  title: string;
  welcomeMessage: string;
  allowedDomains: string[];
  position: 'right' | 'left';
}

export interface ApiConfig {
  rateLimitPerMinute: number;
  keyPrefix: string;
}

export interface EmailConfig {
  inboundAddress: string;
  replyFrom: string;
  /** Replies wait for a person instead of sending straight away. */
  repliesNeedReview: boolean;
  /** Shared mailbox connection (Microsoft 365). */
  folders?: string[];
  securityScan?: boolean;
  archive?: boolean;
  sync?: { status: 'syncing' | 'healthy' | 'error'; lastMessageAt: string | null; messages24h: number; error?: string };
  /** The Microsoft 365 integration holding this mailbox's consent; sync follows its status. */
  connectionId?: string;
  connection?: import('./integrations').ConnectionRef;
}

export interface Deployment {
  id: string;
  name: string;
  workflowId: string;
  workflowName: string;
  channel: DeployChannel;
  environment: DeployEnvironment;
  /** Workflow version this deployment serves. Never a draft. */
  version: number;
  latestVersion: number;
  status: 'active' | 'paused';
  traffic24h: number;
  errors24h: number;
  createdAt: string;
  updatedAt: string;
  widget?: WidgetConfig;
  api?: ApiConfig & { endpoint: string };
  email?: EmailConfig;
  /** MCP deployments: the tool name assistants see. They follow the workflow's release pointer. */
  mcp?: { toolId: string };
  /** Set when the workflow is an agent's wrapper, so rows can read "Agent · <name>". Filled by the API. */
  agentName?: string;
}

export interface DeploymentInput {
  name: string;
  workflowId: string;
  channel: DeployChannel;
  environment: DeployEnvironment;
  widget?: WidgetConfig;
  api?: ApiConfig;
  email?: EmailConfig;
}

export type DeploymentPatch = Partial<Pick<DeploymentInput, 'name' | 'widget' | 'api' | 'email'>> & { status?: Deployment['status']; version?: number; environment?: DeployEnvironment };

// ── Tests and validation ──

export interface TestExpectation {
  /** Whether the run should pause at a review gate. */
  pauses?: 'yes' | 'no';
  /** A tool the run must call. */
  callsTool?: string;
  /** Text the final reply must contain. */
  replyContains?: string;
}

export interface TestCase {
  id: string;
  workflowId: string;
  name: string;
  input: string;
  expect: TestExpectation;
  source: 'manual' | 'run' | 'csv';
  createdAt: string;
}

export type TestCaseInput = Pick<TestCase, 'name' | 'input' | 'expect'>;

export interface TestOutcome {
  passed: boolean;
  paused: boolean;
  toolsCalled: string[];
  reply: string;
  failure?: string;
}

export interface TestResult {
  caseId: string;
  caseName: string;
  draft: TestOutcome;
  live: TestOutcome | null;
  /** Passed on the live version but fails on the draft. */
  regression: boolean;
}

export interface ValidationSummary {
  passed: number;
  total: number;
  regressions: number;
  checksFailing: number;
}

export interface ValidationRun {
  id: string;
  workflowId: string;
  ranAt: string;
  target: 'draft' | 'live';
  results: TestResult[];
  summary: ValidationSummary;
}
