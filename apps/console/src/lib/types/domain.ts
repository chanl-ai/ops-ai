import type { EmailWorkflowConfig } from './cases';
import type { WidgetPin, WidgetSettings } from './widgets';

export type Risk = 'critical' | 'high' | 'medium' | 'low';
export type ReviewStatus = 'pending' | 'in_review' | 'approved' | 'rejected' | 'returned';
export type ReviewKind = 'approval' | 'exception' | 'escalation' | 'policy_override' | 'publish_request' | 'agent_publish' | 'model_validation' | 'skill_publish' | 'template_submission';
export type ReviewDecision = 'approved' | 'rejected' | 'returned';
export type LifecycleStatus = 'live' | 'draft' | 'paused';
export type Channel = 'voice' | 'chat' | 'email' | 'api';
export type ToolAccess = 'read' | 'write';
/** What an agent may be granted: an operation that reads or writes, or a published workflow it starts as a tool. */
export type GrantAccess = ToolAccess | 'workflow';
/** `workflow`: a published workflow exposed to agents; calling it starts a run of that workflow. */
export type ToolType = 'http' | 'code' | 'mcp' | 'workflow';

/** How a workflow behaves when it is called as a tool, from its approval rules. */
export type WorkflowToolApproval = 'pauses_on_writes' | 'pauses_always' | 'runs_without_pause';

export interface Agent {
  /** What the caller may do with this record, from the same check its write routes run; on the detail response only. */
  canEdit?: boolean;
  canDelete?: boolean;
  canPublish?: boolean;
  /** The owning team's name, for a person outside it who cannot look it up in their own teams. */
  teamName?: string | null;
  id: string;
  name: string;
  slug: string;
  role: string;
  instructions: string;
  model: string;
  channels: Channel[];
  toolIds: string[];
  /** Granted tool ids the catalogue no longer offers (unpublished, hidden or deleted); saving the agent drops them. */
  staleToolIds: string[];
  collections: string[];
  /** The owning team: the creator's team from their token. The console names it from the person's teams list. */
  teamId: string | null;
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
  /** Guardrails pinned by version, each with the topics it blocks; enforced on every turn (absent in the mock). */
  guardrailPins?: GuardrailPin[];
  /** The agent's wrapper workflow, once it has been published (see `Workflow.wrapsAgentId`). */
  wrapperWorkflowId?: string;
  /** Workflows that use this agent, with the agent version each one was published with. */
  /** Where the agent runs. `own` is its one-step workflow, which publishes with it: never behind, never republished. */
  usedIn: { workflowId: string; workflowName: string; pinnedVersion: number; status: LifecycleStatus; own?: boolean }[];
  limits: AgentLimits;
  /** Widget templates the agent may fill in chat, by version (c-082); absent in the mock's seeded agents. */
  widgetPins?: WidgetPin[];
  /** Whether the model may compose layouts, and how many widgets one answer may show. */
  widgets?: WidgetSettings;
  memory?: MemorySettings;
  controls: AgentControls;
}

export interface GuardrailPin {
  guardrailId: string;
  version: number;
  name: string;
  topics: string[];
  /** False when the builder switched it off on this version: it is not checked. Absent in the mock: on. */
  enabled?: boolean;
}

/** A guardrail an agent pins by version (agents-service `/v1/guardrails`); kind `blocked_topics` today. */
export interface Guardrail {
  id: string;
  name: string;
  kind: 'blocked_topics';
  owner: string;
  status: 'live' | 'deprecated';
  version: number;
  publishedVersion: number | null;
  /** `scopes`: topic to what it covers and what it does not, listed beside the topic for the classifier. */
  config: { topics: string[]; message: string; scopes?: Record<string, string>; holdUntilChecked?: boolean };
  usedBy: string[];
  /** The open publish request, decided in Reviews. */
  pendingRequestId: string | null;
  /** Every saved version, newest first; agents pin any published one. Absent from the mock, which keeps no guardrails. */
  versions?: GuardrailVersion[];
  updatedAt: string;
}

export interface GuardrailVersion {
  version: number;
  config: Guardrail['config'];
  state: 'draft' | 'published';
  note: string;
  savedBy: string;
  savedAt: string;
  publishedAt: string | null;
  publishedBy: string | null;
}

/**
 * What callers may override on this agent (agents-service `limits`, decision "the agent sets limits; callers
 * override within them"). Saved on the version and published through its review; a value outside them is refused.
 */
/** What the agent remembers about each person (c-124): on by default, and which kinds it saves. */
export interface MemorySettings {
  enabled: boolean;
  kinds: ('fact' | 'preference' | 'episode')[];
}

export interface AgentLimits {
  allowedModels: string[];
  defaultModel: string;
  /** Absent: callers may not set a temperature. */
  temperature?: { min: number; max: number; default: number };
  /** Per run, in US dollars. Absent: no budget is set on the agent. */
  budget?: { ceilingUsd: number; defaultUsd: number };
  allowedKnowledgeBaseIds: string[];
  /** Granted tools a caller may switch off; a caller never adds one. */
  switchableToolIds: string[];
  /** Pinned widgets a caller may switch off (c-082); absent on versions saved before widgets. */
  switchableWidgetIds?: string[];
  callersMayAddInstructions: boolean;
  /** What a public widget key may override. */
  publicKeyMay: AgentPublicKeyOverride[];
}

export type AgentPublicKeyOverride = 'tools' | 'knowledge' | 'budget' | 'outputSchema' | 'variables';

/** What the runtime acts on; the agent page hides every other control. */
export interface AgentControls {
  channels: Channel[];
  guardrails: (keyof AgentGuardrails)[];
  evals: boolean;
}

/** One of the agent's recent threads: a chat with it, or a run of its own graph. */
export interface AgentRun {
  threadId: string;
  kind: 'chat' | 'graph';
  title: string;
  status: string;
  version?: number;
  startedAt: string;
  updatedAt: string;
}

export interface AgentGuardrails {
  redactPii: boolean;
  /** Empty (null) is no cap; a number caps each turn. A real agent may need many. */
  maxToolCallsPerTurn: number | null;
  /** Model requests in one turn; null is no cap. Absent in the mock. */
  maxModelCallsPerTurn?: number | null;
  /** A chat conversation's budget (c-103): empty (null) is the platform default (200 calls, 5.00 cost), never unlimited. */
  maxModelCallsPerConversation?: number | null;
  maxCostPerConversation?: number | null;
  whenUnsure: 'handoff' | 'ask' | 'decline';
  blockedTopics: string[];
}

/** One save of the agent page; every save becomes a new agent version. */
export type AgentPatch = Partial<AgentInput> & {
  toolIds?: string[];
  collections?: string[];
  guardrails?: AgentGuardrails;
  guardrailPins?: { guardrailId: string; version: number; enabled?: boolean }[];
  limits?: AgentLimits;
  /** Each snapshotted from the widget library on save; version absent takes the latest published. */
  widgetPins?: { widgetId: string; version?: number }[];
  widgets?: WidgetSettings;
  memory?: MemorySettings;
  note?: string;
};

export interface AgentInput {
  name: string;
  role: string;
  model: string;
  channels: Channel[];
  instructions?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  /** The owning team: the creator's team from their token. */
  teamId: string | null;
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
  /** v1 is a graph edited at /workflows/<id>; v2 a runner definition edited at /workflows/definitions/<id>. */
  engine?: 'v1' | 'v2';
  /**
   * Set on an agent's wrapper: the one-step "Chat message → Agent → Reply" workflow an agent deploys through.
   * Created by the platform the first time the agent is published; its publish follows the agent's.
   */
  wrapsAgentId?: string;
  /** The wrapped agent's name, filled by the API. */
  wrapsAgentName?: string;
  /** How it starts, read from its trigger (c-466). */
  start?: WorkflowStart;
}

export interface WorkflowStart {
  /** The start form's kind (`email`, `form`, or a later one), or `source` for a trigger only its source starts. */
  kind: string;
  /** Start run and Files offer it: its trigger declares a start form and other workflows are not its only starters. */
  byHand: boolean;
  /** Its start form has a file field, so Files offers to start it with a file. */
  takesFiles: boolean;
}

export interface WorkflowInput {
  name: string;
  trigger: string;
  template: 'blank' | 'approval' | 'triage' | 'chat';
  /** For the chat template: the agent the workflow wraps. */
  agentSlug?: string;
}

export type WorkflowSettingsInput = Pick<Workflow, 'name' | 'description' | 'trigger'>;

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

/**
 * A tool an agent may be granted (GET /v1/tools): a published tools-service operation; `id` is its name. A run hands
 * the model `description` and `inputSchema`, and calls it through the tool gateway.
 */
export interface GrantableTool {
  id: string;
  name: string;
  /** The module the operation belongs to. */
  server: string;
  moduleId: string | null;
  description: string;
  access: GrantAccess;
  /** JSON Schema of the operation's input, as the model receives it. */
  inputSchema: { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };
  /** Whether every call waits for a person's approval. */
  requiresApproval: boolean;
  /** The approval a call waits for, named; null when the operation has no named template. */
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
  /** What the caller may do with this workflow, from the same check its write routes run. */
  canEdit?: boolean;
  canDelete?: boolean;
  canPublish?: boolean;
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

/** Where a review was raised: an agent's write held in a chat conversation, or a workflow's paused step. Publish
 * requests carry none. */
export type ReviewOrigin = { kind: 'chat'; threadId: string; agentName: string } | { kind: 'workflow' };

/** One input a reviewer may set when choosing an option, declared by the API from the operation's input schema. */
/** A typed Human Task (c-288): its type, the regions the server bound from its params, and its actions in order. */
export interface TypedTask {
  type: { id: string; version: number; name: string };
  regions: { region: 'header' | 'why_source' | 'document' | 'facts' | 'write_preview' | 'form' | 'message' | 'history' | (string & {}); collapsed?: boolean; data: Record<string, unknown> }[];
  actions: TaskAction[];
  warnings: { field: string; severity: string; message: string }[];
}

export interface TaskAction {
  name: string;
  label: string;
  consequence?: string | null;
  reason: 'required' | 'optional' | 'none';
  tone: 'primary' | 'neutral' | 'destructive';
  /** The step's port the decision takes; approve and reject are the step's own. */
  port: string;
  inputs?: OptionInput[];
  /** A rule the action waits for, such as key_fields_confirmed. */
  requires?: string | null;
}

export interface OptionInput {
  name: string;
  type: 'string' | 'number' | 'integer' | 'boolean' | (string & {});
  required: boolean;
  default?: unknown;
  minimum?: number | null;
  maximum?: number | null;
  enum?: unknown[] | null;
  /** The field's words when the server gives them ("Send to"); otherwise taken from `name`. */
  label?: string | null;
  /** `person`: one of the team's people, by email; empty means the team queue. */
  format?: string | null;
}

/** One way to decide a step that offers options: its name, the inputs the reviewer may set, the call it makes, and
 * whether choosing it asks for a step-up (its call's policy). A form renders from `inputs`; decide validates them. */
export interface ReviewOption {
  name: string;
  /** The button's words when the server names them (a runner review's options); otherwise taken from `name`. */
  label?: string;
  /** What the reviewer fills in for this option; a runner review's options carry none. */
  inputs?: OptionInput[];
  call?: { tool: string; input: Record<string, unknown>; step: string } | null;
  stepUp?: boolean;
  /** What choosing it does, and the values its call sends, worded by the server (c-289). */
  consequence?: string | null;
  fields?: ActionField[];
  /** A typed task's action (c-288): whether it asks for a reason, and its button's weight. */
  reason?: 'required' | 'optional' | 'none';
  tone?: 'primary' | 'neutral' | 'destructive';
}

/** One value a call would send, labelled and formatted by the server. */
export interface ActionField {
  label: string;
  value: string;
}

/** An operation as a tool module review names it (c-204). */
export interface OperationSummary {
  name: string;
  method?: string | null;
  path?: string | null;
  access: string;
}

/** What a tool module review approves since the published version, as tools-service sent it when it opened. */
export interface ToolModuleDiff {
  added: OperationSummary[];
  removed: OperationSummary[];
  changed: (OperationSummary & { fields: string[] })[];
  hostsAdded: string[];
  secrets: string[];
}

/** Where an open task sits in its queue and its neighbours, from the server; position is null once it has left. */
export interface ReviewPlace {
  position: number | null;
  total: number;
  previous: string | null;
  next: string | null;
}

export interface Review {
  id: string;
  /** Its place in the open queue, when the service sends it with the task (one call); otherwise read from /place. */
  place?: ReviewPlace;
  /** Whether the signed-in person may decide it now, by the decision route's own checks (agents-service); absent from the mock. */
  canDecide?: boolean;
  title: string;
  origin?: ReviewOrigin;
  customer: string;
  workflowId: string;
  workflowName: string;
  agentSlug: string;
  /** Display name of the agent behind `agentSlug`, filled by the API. */
  agentName?: string;
  kind: ReviewKind;
  risk: Risk;
  /** Null for a step no model scored (a v2 workflow's review step). */
  confidence: number | null;
  proposal: string;
  actionTool: string;
  /** What the proposal would move; null from agents-service when the call names no amount. */
  amount?: number | null;
  /** Null when the step read no account, so the amount's currency is not known. */
  currency: string | null;
  policy: Pick<GatePolicy, 'id' | 'name' | 'condition' | 'reviewers' | 'sla' | 'onTimeout' | 'fourEyes'>;
  /** Minutes until the SLA lapses, counted from the request; negative once overdue, null once decided. */
  slaMinutes: number | null;
  assignee?: string;
  approvals: string[];
  status: ReviewStatus;
  createdAt: string;
  /** Who decided it, when and why; set once decided. */
  decidedBy?: string;
  decidedAt?: string;
  decisionReason?: string;
  /** Present on a tool module review: the module and version it publishes. */
  toolModule?: { moduleId: string; version: string; applyPending: boolean; diff?: ToolModuleDiff };
  /** A decided money review: a fingerprint of the step-up it was approved under (never the token); absent when none was needed. */
  stepUpRef?: string;
  reasoning: string[];
  evidence: Evidence[];
  /** Present on publish requests: what would ship and how it tested. */
  publish?: PublishRequestInfo;
  /** True when the operation being approved needs two approvers; the console asks for a step-up first. Set by the API. */
  stepUp?: boolean;
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
  /** A step that offers options: each with the inputs it declares; `calls` the call behind each by name. */
  options?: ReviewOption[] | null;
  calls?: Record<string, { tool: string; input: Record<string, unknown>; step: string }> | null;
  /** The last failed call the step waits again after (a system's 422), as the tool step recorded it. */
  error?: { tool: string; status?: number | null; code?: string | null; message: string } | null;
  /** The option a decided review was decided with; its status stays approved. */
  option?: string | null;
  /** The document read a step asks a person to check (c-169); absent on other reviews. */
  read?: DocumentRead | null;
  /** The reply a step approves, as it will be sent, with the cases the document opened (c-169). */
  reply?: ReplyPreview | null;
  /** The case the review's run is on (agents-service, c-128); null when the run is on no case. */
  caseId?: string | null;
  /** The case's subject on a list grouped by case (c-460); null when the reader's teams do not hold the case. */
  caseTitle?: string | null;
  /** A workflow runner's step: its name and its run, for the sheet's subtitle and link (c-169). */
  stepName?: string | null;
  runId?: string | null;
  /** The workflow version the run pinned (c-074). */
  workflowVersion?: number | null;
  /** The one question the step asks, in a reviewer's words (c-289). */
  question?: string | null;
  /** A typed task's bound regions and actions (c-288); absent on a review whose step names no task type. */
  task?: TypedTask | null;
  /** The file the decision is about: the first file id in the run's input or the step's summary. */
  sourceFile?: string | null;
  /** What approving the step's own call does, and the values it sends (a step without options). */
  consequence?: string | null;
  actionFields?: ActionField[];
  /** The team that decides it: its writes' approving team, else the run's or thread's; name null when unread. */
  decidingTeam?: { id: string; name?: string | null } | null;
}

export interface ReadField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  /** The document type marks it key: a person confirms it on its own before Approve; the rest are accepted together. */
  keyField?: boolean;
}

export interface FieldRead {
  value: unknown;
  extractedValue: unknown;
  /** From the engine's checks on the quote, page and value, never the model's own; null when not scored. */
  confidence: number | null;
  needsReview: boolean;
  citation: { page: number | null; quote: string | null } | null;
  /** The type rule the model's answer broke (c-247); `value` is then null and `extractedValue` holds what it said. */
  rejected?: string | null;
  /** A person corrected it; `value` is theirs and `extractedValue` what was read. */
  corrected?: boolean;
  /** Where the value was read, one box per printed line, as fractions of the page (c-252); absent when not found. */
  boxes?: { page: number; x: number; y: number; w: number; h: number }[];
  /** Each source's value for the field and whether they disagree, when the read was combined with others (c-261). */
  bySource?: Record<string, unknown>;
  conflict?: boolean;
}

export interface DocumentRead {
  fileId: string;
  fileName: string | null;
  /** The confidence a field must reach; fields under it are marked for a check. */
  floor: number | null;
  schema: ReadField[];
  records: { values: Record<string, unknown>; fields: Record<string, FieldRead> }[];
  /** The sources a Combine facts step weighed against this read, in order; empty for one source (c-261). */
  sources?: string[];
  /** The step takes a correction: Approve may send `inputs.edited`, the whole records list. */
  editable: boolean;
  /** The values a decided review was approved with when the reviewer corrected the read; null when none was sent. */
  corrected: Record<string, unknown>[] | null;
}

export interface ReplyPreview {
  to: string;
  mailbox: string | null;
  subject: string;
  body: string;
  /** One per run the document started; caseId is null until that run has opened its case. */
  cases: { runId: string; caseId: string | null; subject?: string | null }[];
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

/** Approve, reject or return; or, on a step that offers `options`, one of them. */
export type ReviewChoice = ReviewDecision | (string & {});

export interface ReviewDecisionInput {
  decision: ReviewChoice;
  reason?: string;
  /** Deciding with an option: the inputs the reviewer set, by the names the option declares; the API validates them. */
  inputs?: Record<string, unknown>;
  /** Model validation only: conditions attached to an approval, and who is deciding (a run-as principal; unset is you). */
  conditions?: import('./model-risk').ConditionInput[];
  actingAsId?: string;
  /** Reject or return only: propose the reviewed input as a draft case in `testTarget`'s suite. */
  addTestCase?: boolean;
  /** Approving a call that needs a step-up: the AuthProvider's token from a re-authentication in the last 5 minutes. */
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
  workflow?: { workflowId: string; tier: Risk; approval: WorkflowToolApproval };
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

/** What waits on a person, counted on the server (agents-service `GET /v1/overview`, c-129). */
export interface Overview {
  openReviews: number;
  overdueReviews: number;
  /** The open reviews soonest past their SLA, as Human Tasks lists them. */
  urgentReviews: Review[];
  /** open: open or waiting on us; breaching: past the resolution deadline and not paused; awaitingApproval: with a review open. */
  cases: { open: number; breaching: number; awaitingApproval: number };
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
  /** Each pinned guardrail and whether this version checks it; absent before guardrails had a switch. */
  guardrailPins?: { guardrailId: string; version: number; name: string; enabled: boolean }[];
  /** What this version changed since the one before it, one line each. */
  changes?: string[];
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
  /** `status` says how each call went (c-170): ok, error, or gated (stopped for a review). */
  toolCalls: { name: string; input: string; output: string; status?: 'ok' | 'error' | 'gated' | 'running'; access?: string }[];
  /** Each citation's knowledge base, page and the words cited (c-170). */
  citations: { source: string; section: string; kbId?: string; kbName?: string; page?: number; quote?: string }[];
  /** The knowledge bases the reply could search (c-170). */
  knowledgeBases?: { id: string; name: string }[];
  /** The tools the agent holds, and which pause for a review, at which gate, for whom (c-170). */
  tools?: { name: string; access: string; pauses: boolean; gate?: string; reviewers?: string }[];
  /** The guardrails the turn checked. */
  guardrails?: { name: string; version?: number }[];
  /** Set when, in production, this turn would pause at a review gate instead of acting. */
  wouldPause?: {
    gate: string;
    reviewers: string;
    /** The review a real run opens for the same call: the tool, what it would do, and whether deciding needs a step-up. */
    tool?: string;
    action?: string;
    stepUp?: boolean;
  };
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
