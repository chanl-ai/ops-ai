import type { Citation } from './knowledge';
import type { RetrievalTrace } from './knowledge-retrieval';
import type { ListParams, ListResult } from './query';
import type { MessagePart } from './widgets';

export type { Citation };

/** A live agent people can chat with, with the knowledge bases it reads by default. */
export interface ChatAgent {
  id: string;
  name: string;
  role: string;
  version: number;
  model: string;
  defaultKbIds: string[];
  /** Knowledge bases this agent may search, with display names; the chat picker and chips use these when present. Includes defaultKbIds. */
  kbs?: { id: string; name: string }[];
  /** Starter prompts shown on the new-chat screen. */
  suggestions: string[];
}

// ── Widgets ──
// A widget is the UI an MCP App returns with a tool result. Production renders the app's HTML in a sandboxed
// iframe served through the tool gateway; the mock renders the same payloads with native components so the
// layout, states and actions can be reviewed without a running app.

interface WidgetBase {
  id: string;
  title: string;
  /** The MCP App (server) that produced the widget. */
  app: string;
  /** The tool call whose result the widget renders. */
  tool: string;
  /** When the data was read from the system of record. */
  asOf: string;
}

export interface TableWidget extends WidgetBase {
  kind: 'table';
  columns: { key: string; label: string; align?: 'left' | 'right'; tone?: boolean }[];
  rows: Record<string, string | number>[];
  /** Where the full list lives in the app. */
  href?: string;
}

export interface ChartWidget extends WidgetBase {
  kind: 'chart';
  chart: 'bar' | 'line';
  xKey: string;
  /** Unit of the value axis, e.g. "Cases". */
  yLabel?: string;
  series: { key: string; label: string }[];
  data: Record<string, string | number>[];
}

export interface RecordWidget extends WidgetBase {
  kind: 'record';
  subtitle?: string;
  status?: string;
  fields: { label: string; value: string }[];
  href?: string;
}

export type ApprovalState = 'pending' | 'awaiting_second' | 'approved' | 'rejected';

/** A drafted action that waits for a person. Deciding it decides the linked review, so the Reviews queue and audit trail stay the record. */
export interface ApprovalWidget extends WidgetBase {
  kind: 'approval';
  reviewId: string;
  action: string;
  summary: string;
  fields: { label: string; value: string }[];
  risk: 'critical' | 'high' | 'medium' | 'low';
  /** Set when approving changes a production system; the approval is confirmed with this text. */
  consequence?: string;
  /** True when the operation being approved needs two approvers; the console asks for a step-up first. Set by the server. */
  stepUp?: boolean;
  state: ApprovalState;
  decidedBy?: string;
  /** Whom the thread waits on while the approval is open: the operation's reviewers, or a second approver. */
  waitingOn?: string;
  /** Whether the reader may decide it now, by the decision route's checks (agents-service); absent from the mock. */
  canDecide?: boolean;
  reason?: string;
}

export interface FormWidgetField {
  key: string;
  label: string;
  type: 'text' | 'select' | 'textarea';
  options?: string[];
  value?: string;
  required?: boolean;
}

export interface FormWidget extends WidgetBase {
  kind: 'form';
  description: string;
  fields: FormWidgetField[];
  submitLabel: string;
  state: 'open' | 'submitted';
  values?: Record<string, string>;
  /** What the submission created, e.g. a case reference. */
  result?: string;
}

export interface MetricWidget extends WidgetBase {
  kind: 'metric';
  metrics: { label: string; value: string; delta?: string; tone?: 'good' | 'bad' | 'neutral' }[];
}

export type ChatWidget = TableWidget | ChartWidget | RecordWidget | ApprovalWidget | FormWidget | MetricWidget;
export type WidgetKind = ChatWidget['kind'];

/** `stepUpToken`: approving a call that needs a step-up needs a re-authentication from the last 5 minutes. */
export type WidgetAction = { type: 'approve'; stepUpToken?: string } | { type: 'reject'; reason: string } | { type: 'submit'; values: Record<string, string> };

// ── Messages ──

export interface ToolCall {
  id: string;
  name: string;
  /** MCP server the tool belongs to. */
  server: string;
  input: Record<string, unknown>;
  output?: unknown;
  status: 'running' | 'success' | 'failed';
  durationMs: number;
  /** Write tools stop at a gate: the call drafts the action and a person decides. */
  gated?: { gate: string; reviewers: string };
}

export interface MessageFeedback {
  rating: 'up' | 'down';
  reason?: string;
}

/** A file uploaded through the Files API; messages carry its id, never its bytes. */
export interface ChatAttachment {
  fileId: string;
  name: string;
  size: number;
}

/** One memory a reply saved about the person (c-206); an episode has no key. */
export interface RememberedItem {
  id: string;
  kind: 'fact' | 'preference' | 'episode';
  key?: string | null;
  value: string;
}

export interface GuardrailAudit {
  kind: 'withheld' | 'retracted';
  text: string;
  guardrail?: { guardrailId: string; version: number; name: string; topic: string; when: 'before' | 'after' | 'corrected' };
  stopReason?: string;
  at?: string;
}

/** One reply's spend, as the thread returns it (c-286). */
export interface ReplyUsage {
  calls: number;
  inputTokens: number;
  outputTokens: number;
  /** Two decimal places of the workspace currency. */
  cost: string;
  seconds?: number | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  at: string;
  /** Assistant messages: the model that answered, as the provider reported it (e.g. gpt-5.5-2026-04-23). */
  model?: string;
  /** What the reply spent (c-286): model calls, tokens, cost and seconds; absent when nothing was recorded. */
  usage?: ReplyUsage;
  /** Assistant messages: the agent that wrote the reply; after a handover it is not the chat's first agent (c-174). */
  agentId?: string;
  agentName?: string;
  /** Assistant messages: what this turn saved about the person, shown under the reply (c-206). */
  remembered?: RememberedItem[];
  attachments?: ChatAttachment[];
  citations?: Citation[];
  /** How the cited passages were found: queries, filters, scores, precedence. */
  trace?: RetrievalTrace;
  toolCalls?: ToolCall[];
  widgets?: ChatWidget[];
  /** Tool results agents-service shaped (rows, series, record, metric), drawn by the widget registry. */
  parts?: MessagePart[];
  feedback?: MessageFeedback;
  /** Retrieval found nothing above the threshold; the reply says so instead of guessing. */
  noAnswer?: boolean;
  /** The person stopped the reply; the text so far is kept. */
  stopped?: boolean;
  /** The reply failed part-way; the text so far is kept. */
  error?: string;
  /** Why the model endpoint refused the reply, e.g. `rate_limited`; kept so a reload reads the same as the stream. */
  errorCode?: string;
  /** The pinned guardrail that refused the question (`before`), replaced the answer with its message (`after`) or had it rewritten once (`corrected`). */
  guardrail?: { guardrailId: string; version: number; name: string; topic: string; when: 'before' | 'after' | 'corrected' };
  /** What a guardrail kept back (`withheld`, never shown) or took back after it was shown (`retracted`). Present only
   *  when the reader may view the audit; the stream never carries it. */
  guardrailAudit?: GuardrailAudit[];
  /** Skills the turn loaded, always-on first. */
  skills?: { skillId: string; name: string; version: number; matched: string }[];
  /** The settings the turn ran on (c-071), for whoever explains the answer later. */
  settings?: EffectiveSettings;
  /** The conversation's budget ran out at this turn (c-103); its numbers are the server's ledger. */
  budget?: BudgetPause;
}

export interface BudgetPause {
  /** The pause's id; an answer names it, so a tab showing an older pause gets 409 stale_pause. */
  id?: string;
  limit: 'calls' | 'tokens' | 'cost';
  spent: string;
  cap: string;
  state: 'waiting' | 'continued' | 'raised';
  answeredBy?: string;
  newCap?: string;
}

/** Continue adds one more allotment (the conversation's owner); raise sets new caps (an admin of its team). */
export type BudgetAnswer = ({ action: 'continue' } | { action: 'raise'; maxCalls?: number; maxCost?: number }) & { pauseId?: string };

export interface ChatThread {
  id: string;
  title: string;
  agentId: string;
  agentName: string;
  agentVersion: number;
  kbIds: string[];
  kbNames: string[];
  pinned: boolean;
  archived: boolean;
  owner: string;
  createdAt: string;
  lastMessageAt: string;
  messageCount: number;
  /** Set while the chat is handed over (c-174): the agent it started on, which Back returns to. */
  startAgentId?: string;
  startAgentName?: string;
  /** A builder's test of the agent (c-284), set by the server: runs the newest draft, left out of counts and memory. */
  test?: boolean;
  messages: ChatMessage[];
}

export type ChatThreadRow = Omit<ChatThread, 'messages'> & { preview: string; widgets: number; citations: number };

export type ChatThreadState = 'active' | 'pinned' | 'archived';

/** Chat lists hold the caller's own chats only, so there is no owner filter. */
export type ChatFilters = { agentId?: string[]; kbIds?: string[]; state?: string[] };

/** `cursor` reads the rows after the one it names, in the list's order; the conversations table pages by `page`. */
export type ChatThreadListParams = ListParams<ChatFilters> & { cursor?: string };

export interface ChatThreadList extends ListResult<ChatThreadRow> {
  /** Set while more rows follow; pass it back as `cursor`. */
  nextCursor?: string;
}

/**
 * What a banker asks for on a thread or one message, within the agent's limits. The server's resolver checks each
 * field and refuses one outside the limits with 422 naming it (`overrides.thread.model`); the settings panel offers
 * only what the limits allow, so a person never builds a request that fails.
 */
export interface ChatOverrides {
  model?: string;
  temperature?: number;
  /** Added after the agent's instructions; never replaces them. */
  instructions?: string;
  /** Granted tools switched off; never added. */
  toolsOff?: string[];
  knowledgeBaseIds?: string[];
  budgetUsd?: number;
  outputSchema?: Record<string, unknown>;
  variables?: Record<string, unknown>;
  /** Pinned widgets switched off, composing switched off, a lower cap: widgets narrow only. */
  widgetsOff?: string[];
  composeOff?: boolean;
  widgetsPerTurn?: number;
}

/** A settings save: a field sent replaces it, null clears it, a field left out keeps what the thread has. */
export type ChatOverridesPatch = { [K in keyof ChatOverrides]?: ChatOverrides[K] | null };

/** The settings a turn ran on, and where each came from: `agent`, `started` (the thread's first bases), `thread` or `turn`. */
export interface EffectiveSettings {
  model: string;
  temperature?: number;
  addedInstructions: string[];
  toolsOff: string[];
  knowledgeBaseIds: string[];
  budgetUsd?: number;
  widgetsOff: string[];
  composeOff: boolean;
  widgetsPerTurn?: number;
  sources: Record<string, string>;
}

export interface NamedRef {
  id: string;
  name: string;
}

/** What the thread's agent lets the banker change, with names, from the API. */
export interface ThreadLimits {
  allowedModels: string[];
  defaultModel: string;
  temperatureMin?: number;
  temperatureMax?: number;
  knowledgeBases: NamedRef[];
  switchableTools: NamedRef[];
  mayAddInstructions: boolean;
  budgetCeilingUsd?: number;
  switchableWidgets: NamedRef[];
  mayCompose: boolean;
  widgetsPerTurn?: number;
}

export interface ThreadSettings {
  limits: ThreadLimits;
  overrides?: ChatOverrides;
  effective: EffectiveSettings;
}

export interface ChatThreadInput {
  /** Left out, the chat starts on the team's default agent (c-174). */
  agentId?: string;
  kbIds: string[];
  /** Test the agent (c-284): granted only to someone who may edit it; each message runs its newest version. */
  test?: boolean;
  /** With `test`, run this saved version instead of the newest (c-286's compare). */
  testVersion?: number;
  title?: string;
  /** Apply to every message in the thread. */
  overrides?: ChatOverrides;
  attachments?: ChatAttachment[];
}

/** `agentId` hands the chat to another agent (an @mention); the agent it started on hands it back (c-174). */
export type ChatThreadPatch = Partial<Pick<ChatThread, 'title' | 'pinned' | 'archived' | 'kbIds' | 'agentId'>>;

/** The agent the team's new chats start on; absent until provisioning or a team admin sets one. */
export interface TeamDefaultAgent {
  agentId?: string;
  /** Absent when that agent is no longer live. */
  agentName?: string;
  /** Whether the caller may change it (chat.manage, decided by agents-service). */
  canChange?: boolean;
}

export interface SendInput {
  content: string;
  attachments?: ChatAttachment[];
  /** This message only; may narrow the thread's overrides. */
  overrides?: ChatOverrides;
  /** Replace this assistant message with a new answer to the question before it. */
  regenerate?: string;
  /** Edit this user message: later messages are dropped and the edited question is answered again. */
  edit?: string;
}

/**
 * One event on a reply stream. The shapes map one-to-one onto the Vercel AI SDK UI message stream parts
 * (text-delta, tool-input-available, tool-output-available, data-*, source-document, finish), so a
 * production client can swap the hook internals for `useChat` with a custom transport.
 */
export type ChatStreamEvent =
  | { type: 'start'; userMessage?: ChatMessage; messageId: string }
  | { type: 'status'; phase: 'thinking' | 'retrieving' | 'calling_tool' | 'writing' | 'checking' }
  | { type: 'tool_start'; call: ToolCall }
  | { type: 'tool_end'; call: ToolCall }
  | { type: 'widget'; widget: ChatWidget }
  | { type: 'part'; part: MessagePart }
  | { type: 'text'; delta: string }
  /** The answer streamed so far is replaced: a guarded answer its after-answer check corrected or refused. What was
   *  shown before it is kept as a `retracted` entry of the message's guardrailAudit, for a reader who may view the audit. */
  | { type: 'replace'; text: string }
  | { type: 'citations'; citations: Citation[] }
  | { type: 'done'; message: ChatMessage }
  | { type: 'error'; message: string; partial: ChatMessage; code?: string };
