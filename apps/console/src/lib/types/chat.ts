import type { Citation } from './knowledge';
import type { RetrievalTrace } from './knowledge-retrieval';

export type { Citation };

/** A live agent people can chat with, with the knowledge bases it reads by default. */
export interface ChatAgent {
  id: string;
  name: string;
  role: string;
  version: number;
  model: string;
  defaultKbIds: string[];
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
  /** Set when approving moves money or changes a production system; the approval is confirmed with this text. */
  consequence?: string;
  state: ApprovalState;
  decidedBy?: string;
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

export type WidgetAction = { type: 'approve' } | { type: 'reject'; reason: string } | { type: 'submit'; values: Record<string, string> };

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

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  at: string;
  attachments?: ChatAttachment[];
  citations?: Citation[];
  /** How the cited passages were found: queries, filters, scores, precedence. */
  trace?: RetrievalTrace;
  toolCalls?: ToolCall[];
  widgets?: ChatWidget[];
  feedback?: MessageFeedback;
  /** Retrieval found nothing above the threshold; the reply says so instead of guessing. */
  noAnswer?: boolean;
  /** The person stopped the reply; the text so far is kept. */
  stopped?: boolean;
  /** The reply failed part-way; the text so far is kept. */
  error?: string;
}

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
  messages: ChatMessage[];
}

export type ChatThreadRow = Omit<ChatThread, 'messages'> & { preview: string; widgets: number; citations: number };

export type ChatThreadState = 'active' | 'pinned' | 'archived';

export type ChatFilters = { agentId?: string[]; kbIds?: string[]; state?: string[]; owner?: string[] };

export interface ChatThreadInput {
  agentId: string;
  kbIds: string[];
  title?: string;
}

export type ChatThreadPatch = Partial<Pick<ChatThread, 'title' | 'pinned' | 'archived' | 'kbIds'>>;

export interface SendInput {
  content: string;
  attachments?: ChatAttachment[];
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
  | { type: 'status'; phase: 'thinking' | 'retrieving' | 'calling_tool' | 'writing' }
  | { type: 'tool_start'; call: ToolCall }
  | { type: 'tool_end'; call: ToolCall }
  | { type: 'widget'; widget: ChatWidget }
  | { type: 'text'; delta: string }
  | { type: 'citations'; citations: Citation[] }
  | { type: 'done'; message: ChatMessage }
  | { type: 'error'; message: string; partial: ChatMessage };
