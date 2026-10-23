import type { StoryLine } from './engine';

/** A team's customer issue (agents-service `/v1/cases`, c-128): who it is for, who works it, and its two deadlines. */
export type CaseStatus = 'open' | 'waiting_on_customer' | 'waiting_on_us' | 'resolved' | 'closed';
export type CasePriority = 'low' | 'normal' | 'high' | 'urgent';

export interface CaseRecord {
  id: string;
  teamId: string;
  subject: string;
  customerId: string | null;
  customerName: string | null;
  status: CaseStatus;
  /** By email. */
  assignee: string | null;
  /** The assignee by name, joined by the list (GET /v1/cases, c-403); a person the platform cannot name keeps the email. */
  owner?: { email: string; name: string } | null;
  priority: CasePriority;
  responseDueAt: string;
  resolutionDueAt: string;
  respondedAt: string | null;
  /** Set while the case waits on the customer: both deadlines are paused from then. */
  pausedSince: string | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  /** Seconds to each deadline, negative once past; null while paused, once met, or once the case is resolved. */
  responseLeftS: number | null;
  resolutionLeftS: number | null;
  /** What a workflow read and worked out for the case (Open case / Add to case, c-259), by name; null when none. */
  fields?: Record<string, unknown> | null;
}

/** One timeline entry: opened, a field change, a note, a run, chat or decision the case covers, or a link. */
export interface CaseEvent {
  id: string;
  kind: string;
  ref: string | null;
  detail: Record<string, unknown>;
  by: string;
  at: string;
}

/** One clock as the server states it (c-291): running, met, breached or paused, with seconds left while running. */
export interface CaseClock {
  state: 'running' | 'met' | 'breached' | 'paused' | (string & {});
  dueAt: string;
  leftS: number | null;
  metAt: string | null;
}

/** A case value in the case type's order, with its display text formatted on the server. */
export interface CaseTypedField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'money' | 'date' | 'enum' | 'file' | 'link' | (string & {});
  display: string;
  raw: unknown;
  fileId: string | null;
  required: boolean;
  /** False for a value the case type does not list. */
  declared: boolean;
  edited: boolean;
}

export interface CaseWaitingTask {
  taskId: string;
  title: string;
  assignee: { name: string } | null;
  group: string | null;
  openedAt: string;
  dueAt: string | null;
  href: string;
}

export interface CaseDraftedAction {
  id: string;
  taskId: string;
  label: string;
  kind: 'reply' | 'tool' | (string & {});
  /** `refused`: approved, but the call it sent answered an error (the bank refused the hold). */
  status: 'pending' | 'approved' | 'refused' | 'rejected' | (string & {});
  approvalsGiven: number;
  approvalsNeeded: number;
  summary: string | null;
  href: string;
}

/**
 * One case as its page shows it (GET /v1/cases/{id}, c-291): assembled on the server, so the page joins nothing. The
 * page keys arrive with c-291; a service without them still returns the base record and events.
 */
export interface CaseRecordDetail extends CaseRecord {
  events: CaseEvent[];
  caseType?: { id: string; version: number; name: string } | null;
  team?: { id: string; name: string };
  customer?: { id: string; name: string; href: string } | null;
  sla?: { response: CaseClock; resolution: CaseClock; pausedSince: string | null };
  typedFields?: CaseTypedField[];
  waiting?: CaseWaitingTask[];
  waitingAllHref?: string | null;
  actions?: CaseDraftedAction[];
  links?: {
    files: { fileId: string; name: string | null; viewerHref: string }[];
    runs: { id: string; workflowName: string; state: string; href: string }[];
    emails: { id: string; subject: string; direction: string; at: string; href: string }[];
    cases: { id: string; subject: string; status: string; relation: 'linked' | 'same_customer' | (string & {}); href: string }[];
    allHrefs: { runs: string; emails: string; cases: string | null };
  };
  workflow?: { id: string; name: string; href: string } | null;
  /** The case's one timer (c-500): its type's deadline field, else the resolution clock. */
  timer?: { label: string; dueAt: string; state: CaseClock['state']; leftS: number | null };
  /** What is left: open Human Tasks and refused actions, who and by when; `resolvable` when nothing is. */
  whatsLeft?: { items: { kind: 'task' | 'action'; who: string; what: string; dueAt: string | null; href: string }[]; resolvable: boolean };
  /** How the case's work began: the first run of the chain that opened it, or who opened it by hand. */
  origin?: { kind: string; text: string; runId: string | null; href: string | null };
  /** Everything that happened to the case, newest first, in the run story's sentences. */
  feed?: { lines: StoryLine[]; more: number };
  permissions?: { assign: boolean; changeStatus: boolean; close: boolean; note: boolean };
}

export interface CaseRecordFilters {
  /** Subject, customer name or customer id. */
  search?: string;
  status?: CaseStatus[];
  priority?: CasePriority[];
  assignee?: string;
  overdue?: boolean;
}

export interface CaseRecordPatch {
  status?: CaseStatus;
  priority?: CasePriority;
  assignee?: string | null;
}
