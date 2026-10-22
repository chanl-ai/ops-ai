// The workflow runner (agents-service /v1/workflows/node-types, /v1/workflows/definitions, /v1/runs): v2 definitions
// built from registered node types, and runs recorded step by step. v1 workflows stay in domain.ts.

export interface EnginePort {
  name: string;
  /** The connection type, e.g. `main`. */
  connection: string;
  label: string;
}

/** A field of a node type's generated form. `item` is the form of each object in a `list`. */
export interface NodeFormField {
  label: string;
  widget: 'text' | 'textarea' | 'number' | 'date' | 'select' | 'switch' | 'mapping' | 'mappings' | 'list' | 'options' | 'source' | 'json';
  help?: string;
  placeholder?: string;
  /** Where a `source` field's choices come from: GET /v1/workflows/option-sources, or the definition's own steps. */
  source?: OptionSource;
  item?: NodeForm;
}

/** The form the console generates for a node type's parameters: one field per parameter, in order. */
export interface NodeForm {
  order: string[];
  fields: Record<string, NodeFormField>;
}

export type OptionSource = 'agents' | 'tools' | 'knowledge' | 'workflows' | 'steps' | 'mailboxes';

export interface EngineOption {
  value: string;
  label: string;
  description: string;
}

/** A port that comes or goes with one of the step's settings. */
export interface PortRule {
  parameter: string;
  value: unknown;
  port: string;
}

export interface EngineNodeType {
  id: string;
  version: number;
  group: string;
  label: string;
  description: string;
  inputs: EnginePort[];
  outputs: EnginePort[];
  /** A list parameter whose entries become the out ports (a review's options); `outputs` is its default. */
  outputsFrom: string | null;
  /** Out ports every instance has after its own, such as a switch's `otherwise`. */
  extraOutputs?: string[];
  /**
   * An extra out port the instance has while `parameter` is `value` (a review's `timeout` when it expires). `value` may be
   * any JSON value; `"*"` means the parameter is set to anything.
   */
  optionalOutputs?: PortRule[];
  /** A port of `outputs` the instance does not have while `parameter` is `value` (Run workflow's `started` when it waits). */
  outputsUnless?: PortRule[];
  /** JSON Schema of the node's parameters. */
  parameters: Record<string, unknown>;
  effects: string;
  retry: { attempts: number; backoffSeconds: number[] };
  executor: string;
  timeoutSeconds: number;
  ui: NodeForm;
}

export interface EngineNode {
  id: string;
  type: string;
  typeVersion: number;
  name?: string;
  parameters?: Record<string, unknown>;
  /** Where the editor last placed it; the runner ignores it. */
  position?: { x: number; y: number };
}

export interface EngineConnection {
  from: { node: string; port: string };
  to: { node: string; port: string };
}

export interface EngineDefinition {
  schemaVersion: 2;
  id: string;
  name?: string;
  nodes: EngineNode[];
  connections: EngineConnection[];
  [key: string]: unknown;
}

export interface DefinitionCheck {
  /** Null for a check about the whole definition. */
  node: string | null;
  level: string;
  code: string;
  message: string;
  /** The top-level parameter a schema error names, so the editor shows the message under that field. */
  field?: string | null;
}

export interface DefinitionValidation {
  ok: boolean;
  workflowId: string | null;
  digest: string | null;
  checks: DefinitionCheck[];
}

export interface DefinitionPublished {
  workflowId: string;
  version: number;
  digest: string;
  /** False when this exact definition was stored before. */
  created: boolean;
}

/** A version's stage: saved as a draft, in review while a publish request for it is open, live or paused once approved. */
export type DefinitionStage = 'draft' | 'in_review' | 'live' | 'paused' | 'superseded';

export interface DefinitionView {
  workflowId: string;
  name: string;
  version: number;
  digest: string;
  stage: DefinitionStage;
  definition: EngineDefinition;
  versions: { version: number; digest: string; createdAt: string; createdBy: string; stage: DefinitionStage }[];
  /** The version live runs start on; null before the first approval. */
  liveVersion: number | null;
  paused: boolean;
  /** The open publish request, if any. */
  review: { id: string; version: number; requestedBy: string; createdAt: string } | null;
  /** How a person starts it by hand; null for a trigger only its source starts. */
  startForm?: StartForm | null;
}

export interface DefinitionPublishRequest {
  id: string;
  status: string;
}

export interface EngineRunInput {
  workflowId: string;
  version?: number;
  input?: Record<string, unknown>;
  runKey?: string;
  mode?: 'live' | 'test';
}

/**
 * How a person starts a workflow by hand, as its trigger declares it (c-466): the dialog's title and button, how a run
 * started this way reads in audit, and the form as JSON Schema. The console draws any kind from this alone.
 */
export interface StartForm {
  /** The adapter that runs it, such as email (a test email) or form (the trigger's input schema). */
  kind: string;
  title: string;
  action: string;
  /** How a run started this way reads: "test email", "form". */
  via: string;
  schema: Record<string, unknown>;
  takesFiles: boolean;
}

/** `POST /v1/runs/start`: the start form's values, run through the same entry the trigger's real source uses. */
export interface StartWorkflowInput {
  workflowId: string;
  version?: number;
  mode?: 'live' | 'test';
  values: Record<string, unknown>;
}

export interface EngineRunStarted {
  runId: string;
  workflowId: string;
  version: number;
  digest: string;
  status: string;
  created: boolean;
}

/** `GET /v1/runs`: one workflow, any of several statuses, a page at a time. */
export interface EngineRunsParams {
  workflowId?: string;
  status?: string[];
  page?: number;
  pageSize?: number;
}

export interface EngineRun {
  id: string;
  /** The workflow's display name when the server joins it; the id is shown without it. */
  workflowName?: string;
  /** Who or what started it, named by the server: the parent run's workflow, a mailbox, an agent, a person or a key. */
  startedBy?: { kind: 'run' | 'trigger' | 'agent' | 'person' | 'key'; id: string; name: string; runId?: string };
  /** Whether the signed-in person may cancel it now (runs/cancel, from agents-service); absent from the mock. */
  canCancel?: boolean;
  workflowId: string;
  version: number;
  digest: string;
  mode: string;
  status: string;
  outcome: string | null;
  error: string | null;
  input: Record<string, unknown> | null;
  output: unknown;
  waiting: { node: string; iteration: number; payload: Record<string, unknown> } | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  finishedAt: string | null;
}

export interface EngineStepAttempt {
  attempt: number;
  status: string;
  effects: string;
  key: string;
  port: string | null;
  input: unknown;
  output: unknown;
  error: string | null;
  startedAt: string;
  finishedAt: string | null;
}

/** One node's step in a run, at one iteration: its last attempt's result, with every attempt below. */
export interface EngineRunStep {
  nodeId: string;
  iteration: number;
  status: string;
  port: string | null;
  input: unknown;
  output: unknown;
  error: string | null;
  attempts: EngineStepAttempt[];
}

export interface EngineRunDetail extends EngineRun {
  steps: EngineRunStep[];
  /** Once the run has succeeded: the End step it finished on, its outcome and output. */
  result: { node: string | null; name: string | null; outcome: string; output: unknown } | null;
  /** The runs its steps started (Start workflow, once or for each item), in step and item order, each with its status. */
  children?: { nodeId: string; index: number; runId: string; status: EngineRun['status']; outcome: string | null }[];
  /** The files the run was given, in the order its input names them, with the name an upload gave. */
  files?: { id: string; name: string | null }[];
  /** Each Human Task decided in the run: who (named), when, why, and the task it was made on. */
  decisions?: { nodeId: string; iteration: number; reviewId: string; action: string; reason: string | null; by: { kind: string; id: string; name: string } | null; at: string | null }[];
}
