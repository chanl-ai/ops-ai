import type { WorkflowRun } from './domain';
import type { ScanStatus } from './files';
/** Email-to-workflow: how an email workflow is configured, and the cases it produces. */

// ── Configuration (lives on the workflow graph, so it is drafted, tested and published with it) ──

export interface IntentField {
  key: string;
  label: string;
  required: boolean;
}

export interface Intent {
  id: string;
  name: string;
  description: string;
  /** Example emails the classifier learns the intent from; 2 to 5. */
  examples: string[];
  fields: IntentField[];
  /** Actions the agent drafts for this intent (tool names, or 'send_reply'). */
  actions: string[];
}

export type CasePriority = 'urgent' | 'high' | 'normal' | 'low';

export interface RouteRule {
  intentId: string;
  queue: string;
  priority: CasePriority;
  slaHours: number;
  /** SLA clock counts business hours only. */
  businessHours: boolean;
}

export type ActionKind = 'reply' | 'tool';

export interface ApprovalRule {
  id: string;
  /** Tool name, or 'send_reply' for outgoing email. */
  action: string;
  label: string;
  kind: ActionKind;
  approverGroup: string;
  /** Two approvers from the group. */
  fourEyes: boolean;
  /** Below this amount the action runs without sign-off; null means always ask. */
  autoApproveBelow: number | null;
}

export interface EmailWorkflowConfig {
  intents: Intent[];
  routes: RouteRule[];
  /** Fallback when the classifier is unsure. */
  fallbackQueue: string;
  confidenceThreshold: number;
  approvals: ApprovalRule[];
}

// ── Sample mail test ──

export interface SampleMailInput {
  from: string;
  subject: string;
  body: string;
}

export interface SampleMailResult {
  intentId: string | null;
  intentName: string;
  confidence: number;
  belowThreshold: boolean;
  fields: { key: string; label: string; value: string | null }[];
  queue: string;
  priority: CasePriority;
  slaHours: number;
  actions: { label: string; kind: ActionKind; needsApproval: boolean; approverGroup?: string; fourEyes: boolean }[];
  tookMs: number;
}

// ── Cases ──

export type CaseStatus = 'new' | 'in_progress' | 'waiting_approval' | 'waiting_customer' | 'closed';

/** An email attachment, stored once by the Files API; the case holds its file id. */
export interface Attachment {
  fileId: string;
  name: string;
  /** Bytes. */
  size: number;
  mime: string;
  scan: ScanStatus;
  /** AI summary of the attachment's content; empty when the scan blocked it. */
  summary: string;
  /** Set while the file is quarantined: why the content is not available. */
  blocked?: string;
}

export interface CaseMessage {
  id: string;
  direction: 'inbound' | 'outbound';
  from: string;
  to: string;
  at: string;
  subject: string;
  body: string;
  attachments: Attachment[];
}

export type ActionStatus = 'drafted' | 'awaiting_second' | 'approved' | 'executed' | 'rejected' | 'failed';

export interface CaseAction {
  id: string;
  kind: ActionKind;
  label: string;
  /** Tool name, or 'send_reply'. */
  tool: string;
  /** Pretty-printed JSON for tools; the draft text for replies. */
  input: string;
  evidence: string[];
  needsApproval: boolean;
  approverGroup?: string;
  fourEyes: boolean;
  approvals: { by: string; at: string }[];
  status: ActionStatus;
  result?: string;
  rejectedReason?: string;
  /** Set when the action changes a production system; approving it asks for confirmation with this text. */
  consequence?: string;
}

export interface CaseEvent {
  at: string;
  kind: 'received' | 'classified' | 'routed' | 'drafted' | 'approved' | 'rejected' | 'executed' | 'assigned' | 'edited' | 'replied' | 'closed';
  text: string;
  by: string;
}

export interface CaseField {
  key: string;
  label: string;
  value: string | null;
  /** True when a person changed the extracted value. */
  edited: boolean;
}

export interface CaseRow {
  id: string;
  subject: string;
  requester: string;
  requesterEmail: string;
  account: string | null;
  workflowId: string;
  workflowName: string;
  mailbox: string;
  intentId: string;
  intentName: string;
  confidence: number;
  queue: string;
  priority: CasePriority;
  status: CaseStatus;
  assignee: string | null;
  receivedAt: string;
  slaDueAt: string;
  /** Minutes until the SLA lapses; negative once breached. Null when closed, or paused while waiting on the customer. */
  slaMinutes: number | null;
  pendingApprovals: number;
  /** Pending actions the current user may approve now. */
  awaitingMe: number;
  /** The workflow run this email started; the case is that run's email, fields and drafted actions. */
  runId?: string;
}

export interface CaseDetail extends CaseRow {
  fields: CaseField[];
  messages: CaseMessage[];
  actions: CaseAction[];
  events: CaseEvent[];
}

export type CaseView = 'mine' | 'team' | 'breaching' | 'awaiting_me' | 'closed';

export type CaseFilters = { queue?: string[]; intentId?: string[]; status?: string[]; priority?: string[] };

export interface CaseViewCounts {
  mine: number;
  team: number;
  breaching: number;
  awaiting_me: number;
  closed: number;
}

export interface CaseStats {
  open: number;
  breaching: number;
  awaitingApproval: number;
  closedToday: number;
}

export type ActionDecision = 'approve' | 'reject';

// ── Runs across workflows (the Cases page) ──

/** A run as the Cases page shows it: the run itself, plus who it waits on and the SLA it runs against. */
export type RunState = 'running' | 'waiting' | 'done' | 'failed';

export type RunView = 'needs_person' | 'open' | 'past_sla' | 'done_today';

export interface RunRow extends WorkflowRun {
  workflowName: string;
  state: RunState;
  /** Reviewer, assignee or queue the run is paused for; null when nothing waits on a person. */
  waitingOn: string | null;
  queue: string | null;
  assignee: string | null;
  slaDueAt: string | null;
  /** Minutes until the SLA lapses; negative once overdue. Null when no SLA applies or the clock is paused. */
  slaMinutes: number | null;
  /** Agent actions that ran (auto-approved or signed off) and those still waiting for sign-off. */
  actionsApproved: number;
  actionsPending: number;
  /** Email case for runs started by a mailbox; its page holds the email, fields and drafted actions. */
  caseId: string | null;
  /** A child run names its parent; a parent lists the runs it opened with each one's current outcome. */
  parentThreadId?: string | null;
  children?: ChildThread[] | null;
}

/** `parent` lists the runs one run opened. */
export type RunRowFilters = { workflowId?: string[]; state?: string[]; queue?: string[]; parent?: string[] };

/** A workflow the runtime can start, with the input its first node reads. */
export interface StartableWorkflow {
  name: string;
  title: string;
  /** `agent` is a published agent's own graph, `agent:<id>`. */
  kind: 'code' | 'definition' | 'agent';
  latestVersion: number | null;
  /** `email` is the `{ sender, subject, body }` object; `agent` is an agent id. */
  input: { name: string; label: string; type: 'text' | 'email' | 'agent'; required: boolean }[];
}

/** Starts one run of a workflow the runtime can run; `input` is what that workflow's first node reads. */
export interface StartRunInput {
  workflowId: string;
  /** Shown as the run's subject in Cases. */
  subject: string;
  input: Record<string, unknown>;
}

export interface RunViewCounts {
  needs_person: number;
  open: number;
  past_sla: number;
  done_today: number;
}

// ── A run's thread state (`GET /v1/threads/{id}/state`) ──
// The keys are the ones the workflow's nodes write (`ops_agents.graphs.definition.WorkflowState`), so they stay
// snake_case: the state is the graph's own object, not a console row. Beyond the engine's own fields below, a
// workflow writes whatever its nodes read and found (an intake's records and matches, a case's customer and hold);
// the console draws those as widget parts by shape, never by name.

/** An object as a tool answered it; the keys are the system's own. */
export type StateObject = Record<string, unknown>;

/** A child thread a run opened: as recorded at open time, with its finish laid over once it ends. */
export interface ChildThread {
  threadId: string | null;
  customerId?: string | null;
  name?: string | null;
  caseNo?: string | null;
  subject?: string | null;
  status: string | null;
  outcome: string | null;
  [key: string]: unknown;
}

/** A tool call that failed, as the tool step recorded it: the system's own status and message. */
export interface ToolFailure {
  tool: string;
  status?: number | null;
  code?: string | null;
  message: string;
}

/** The call behind one decision option, its input the one the approval token is minted over. */
export interface OptionCall {
  tool: string;
  input: Record<string, unknown>;
  step: string;
}

/** The engine's own fields of a run's state; everything else is the workflow's, drawn by shape. */
export interface RunValues {
  status?: string | null;
  tool_error?: ToolFailure | null;
  decision?: { decision: string; call?: OptionCall; approval_token?: string } | null;
  [key: string]: unknown;
}

/** The step a run waits on; what it offers a reviewer is read from its Review row, not from here. */
export interface RunInterrupt {
  id: string;
  payload: {
    kind?: string;
    node?: string;
    error?: ToolFailure | null;
    [key: string]: unknown;
  };
}

export interface RunThreadState {
  threadId: string;
  graph: string;
  version: number | null;
  status: string;
  values: RunValues;
  next: string[];
  interrupt: RunInterrupt | null;
}
