// A widget part carries a shape and its data, never a tool or component name: agents-service shapes tool results,
// and the console picks how to draw them (components/chat/widget-registry.ts). Contract: c-055 spec.md.

export type WidgetShape = 'rows' | 'series' | 'record' | 'metric' | 'form' | 'decision' | 'steps';

export type Cell = string | number | boolean | null;

/** Flat objects, one per row. */
export type Rows = Record<string, Cell>[];

/** One x axis and one or more numeric series over it, each `y` as long as `x`. */
export interface Series {
  x: (string | number)[];
  series: { name: string; y: number[] }[];
}

/** One object whose keys are its field labels. */
export type RecordData = Record<string, Cell>;

export interface Metric {
  value: number;
  unit?: string;
  /** Change against the previous period, in the same unit. */
  delta?: number;
  label: string;
}

/** A JSON schema object with flat properties, and the values the form opens with. */
export interface FormSpec {
  schema: {
    type: 'object';
    properties: Record<string, { type: 'string' | 'number' | 'integer' | 'boolean'; title?: string; description?: string; enum?: (string | number)[] }>;
    required?: string[];
  };
  defaults?: Record<string, Cell>;
}

/** A drafted write waiting for a person; deciding it decides the hold. */
export interface Decision {
  summary: string;
  action: string;
  args: Record<string, unknown>;
  holdId: string;
}

export type StepState = 'pending' | 'running' | 'done' | 'failed';
export type Steps = { title: string; state: StepState }[];

export interface ShapeData {
  rows: Rows;
  series: Series;
  record: RecordData;
  metric: Metric;
  form: FormSpec;
  decision: Decision;
  steps: Steps;
}

export interface WidgetHint {
  /** A renderer id; used when it can draw this shape, otherwise the shape's default. */
  prefer?: string;
  title?: string;
  /** For rows drawn as a chart: the x key and the numeric keys. */
  x?: string;
  y?: string[];
  /** Rows only: how many rows the result had before agents-service cut it to the rows sent. */
  truncatedFrom?: number;
}

export type WidgetPart = {
  [S in WidgetShape]: { type: 'widget'; id: string; shape: S; data: ShapeData[S]; hint?: WidgetHint; schema?: unknown };
}[WidgetShape];

// ── Layouts (c-082, .codeloop/wiki/concepts/chat-widgets.md) ──
// A tree of catalogue primitives the kernel checked before sending (ops_agent_kernel.layout): filled from one of the
// agent's widget templates (`template` names it) or composed by the model. Nothing outside these node types can arrive.

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
export type ColumnFormat = 'text' | 'number' | 'money' | 'date' | 'percent';

export type LayoutNode =
  | { type: 'card'; title?: string; children: LayoutNode[] }
  | { type: 'row' | 'column'; gap?: 'sm' | 'md' | 'lg'; align?: 'start' | 'center' | 'end' | 'between'; children: LayoutNode[] }
  | { type: 'title' | 'text' | 'caption'; text: string }
  | { type: 'badge'; text: string; tone?: Tone }
  | MetricNode
  | TableNode
  | ChartNode
  | { type: 'keyValue'; items: { label: string; value: Cell }[] }
  | { type: 'list'; items: Cell[] }
  | { type: 'button'; label: string; reply: { text: string; values?: Record<string, Cell> }; requires?: string }
  | { type: 'divider' }
  | { type: 'image'; alt: string }
  | KindNode;

// ── Widget kinds (c-176): generic, schema-driven, the same in any industry. Each mirrors its JSON Schema in
// ops_agent_kernel.kinds (copied to lib/widgets/kinds.schema.json and compared in the kernel's tests). ──

export type StepStateKind = 'pending' | 'active' | 'done' | 'failed';
/** A button's message back to the agent; the only thing a kind can do. */
export interface KindAction {
  label: string;
  reply: string;
}
export interface KindStatus {
  text: string;
  tone?: Tone;
}
export interface Pair {
  label: string;
  value: Cell;
  /** Where the value opens, when it names a record (a case, a run). */
  href?: string;
}

export type MetricNode = { type: 'metric'; label: string; value: number | string; unit?: string; delta?: number; deltaLabel?: string; goodWhen?: 'up' | 'down'; trend?: number[] };
export type TableNode = { type: 'table'; rows: Rows; columns?: { key: string; label?: string; format?: ColumnFormat }[] };
export type ChartNode = { type: 'chart'; rows: Rows; x: string; y: string[]; kind?: 'line' | 'bar' | 'area' };

export type KindNode =
  | { type: 'timeline'; title?: string; events: { at: string; title: string; detail?: string; tone?: Tone }[] }
  | { type: 'tracker'; title?: string; reference?: string; steps: { label: string; state: StepStateKind; detail?: string; at?: string }[] }
  | { type: 'entity'; title: string; subtitle?: string; category?: string; status?: KindStatus; fields: Pair[]; actions?: KindAction[] }
  | { type: 'comparison'; title?: string; attributes: string[]; options: { name: string; badge?: string; recommended?: boolean; values: Record<string, Cell>; action?: KindAction }[] }
  | { type: 'checklist'; title?: string; items: { label: string; done: boolean; detail?: string }[] }
  | {
      type: 'form';
      title?: string;
      fields: { name: string; label: string; type: 'text' | 'textarea' | 'number' | 'date' | 'select' | 'boolean'; options?: string[]; required?: boolean; placeholder?: string }[];
      submit: KindAction;
    }
  /** `actionsOff`: the page around it owns the decision (a Human Task's footer), so the card draws no buttons. */
  | { type: 'confirm'; title: string; summary?: string; details?: Pair[]; tone?: Tone; confirm: KindAction; cancel?: KindAction; actionsOff?: boolean }
  | { type: 'document'; name: string; page?: number; pages?: number; before?: string; passage: string; after?: string; fileId?: string }
  | { type: 'quote'; passage: string; source: string; page?: number; confidence?: number; fileId?: string }
  | { type: 'plan'; title: string; description?: string; steps: { label: string; state: StepStateKind; detail?: string }[]; action?: KindAction }
  | { type: 'reasoning'; title?: string; steps: { label: string; detail?: string; state: 'done' | 'active' | 'pending'; results?: string[] }[] }
  | { type: 'slots'; title: string; timezone?: string; reply: string; days: { day: string; slots: { label: string; available: boolean }[] }[] }
  | {
      type: 'receipt';
      title: string;
      number?: string;
      date?: string;
      party?: string;
      currency: string;
      lines: { label: string; quantity?: number; unitPrice?: number; amount: number }[];
      subtotal?: number;
      tax?: number;
      total: number;
      status?: KindStatus;
    }
  /** A file's pages with boxes over the values in question (documents-service's c-252 boxes). */
  | { type: 'viewer'; fileId: string; name?: string; mime?: string; boxes?: { key: string; page: number; x: number; y: number; w: number; h: number; check?: boolean }[] }
  /** Values read from a document for a person to check and correct: the read check's table. */
  | { type: 'field_check'; read: import('./domain').DocumentRead }
  | { type: 'contact'; name: string; role?: string; organisation?: string; phone?: string; email?: string; address?: string; hours?: string; actions?: KindAction[] };

/** Every kind an agent can emit with `present {kind, data}`. */
export type WidgetKind = MetricNode['type'] | TableNode['type'] | ChartNode['type'] | KindNode['type'];

export interface WidgetTemplateRef {
  id: string;
  version: number;
  name: string;
}

export interface LayoutPart {
  type: 'widget';
  id: string;
  layout: LayoutNode;
  /** Present when the layout was filled from a published template; absent when the agent composed it. */
  template?: WidgetTemplateRef;
  /** Present when the agent showed one generic kind (`present {kind, data}`, c-176). */
  kind?: WidgetKind;
}

/** Any part a message carries: a shape the registry draws, or a checked layout. */
export type MessagePart = WidgetPart | LayoutPart;

export const isLayoutPart = (p: MessagePart): p is LayoutPart => 'layout' in p && !!p.layout;

// ── Widget templates (c-082) ──

/** A template node: a LayoutNode whose fields may hold `{ "$bind": "/json/pointer" }` into the template's data. */
export type TemplateNode = { type: LayoutNode['type'] } & Record<string, unknown>;

export type WidgetStatus = 'draft' | 'in_review' | 'published' | 'deprecated';

/** A widget template version a builder authors and an agent pins. Published only after a second person approves it. */
export interface WidgetTemplate {
  /** What the caller may do with this record, from the same check its write routes run; on the detail response only. */
  canEdit?: boolean;
  canDelete?: boolean;
  canPublish?: boolean;
  widgetId: string;
  version: number;
  name: string;
  /** The line the agent's present tool reads to know when to use it (the implicit skill). */
  useWhen: string;
  tree: TemplateNode;
  /** JSON Schema (type object) the data the model fills must match. */
  dataSchema: Record<string, unknown>;
  /** Data the preview fills the template with. */
  sample?: Record<string, unknown>;
  /** Tools the widget's buttons ask the agent to use; an agent pins it only when it holds them all. */
  requiresTools?: string[];
  /** Absent on the agents-service library, which serves published templates only. */
  status?: WidgetStatus;
  updatedBy?: string;
  updatedAt?: string;
}

export type WidgetTemplateInput = Pick<WidgetTemplate, 'name' | 'useWhen' | 'tree' | 'dataSchema' | 'sample'>;

/** An agent version's widgets: pinned templates, whether the model may compose, and how many one answer may show. */
export interface WidgetPin {
  widgetId: string;
  version: number;
  name: string;
  requiresTools?: string[];
}
export interface WidgetSettings {
  compose: boolean;
  /** null: no cap; the agent's own setting is the only limit. */
  perTurn: number | null;
}
