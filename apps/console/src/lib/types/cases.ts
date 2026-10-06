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
  /** Two approvers from the group; required for anything that moves money. */
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
  /** Set when the action moves money or changes a production system; approving it asks for confirmation with this text. */
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
