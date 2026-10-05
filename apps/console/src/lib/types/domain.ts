import type { EmailWorkflowConfig } from './cases';

export type Risk = 'critical' | 'high' | 'medium' | 'low';
export type ReviewStatus = 'pending' | 'in_review' | 'approved' | 'rejected' | 'returned';
export type ReviewKind = 'approval' | 'exception' | 'escalation' | 'policy_override' | 'publish_request' | 'model_validation';
export type ReviewDecision = 'approved' | 'rejected' | 'returned';
export type LifecycleStatus = 'live' | 'draft' | 'paused';
export type Channel = 'voice' | 'chat' | 'email' | 'api';
export type ToolAccess = 'read' | 'write' | 'money_movement';
export type ToolType = 'http' | 'code' | 'mcp';

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
  status: LifecycleStatus;
  version: number;
  updatedAt: string;
  tasks24h: number;
  autoResolvedRate: number;
  workflowIds: string[];
  guardrails: AgentGuardrails;
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
  /** Present on model validation reviews (second-line approval by Model Risk). */
  modelValidation?: import('./model-risk').ModelValidationRequest;
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
}

// ── Deployments ──

export type DeployChannel = 'widget' | 'api' | 'email';
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
