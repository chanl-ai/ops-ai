/**
 * The sample-data engine's own shapes: platform suites, drafts against live, p95 and per-version cost. The service
 * keeps none of these; the engine answers the console's contract (types/evals.ts) through its mapping and feeds
 * assurance, publish and model risk, which still draw suites and injection results from it.
 */

export type EvalCheckType = 'calls_tool' | 'not_calls_tool' | 'cites' | 'reply_contains' | 'reply_not_contains' | 'refuses' | 'extracts' | 'rubric' | 'judge';

/** One argument the tool call must carry, e.g. `amount` equals `1240.18`. */
export interface ArgMatcher {
  path: string;
  equals: string;
}

/** One expectation on a case. Only the fields its `type` needs are set. */
export interface EvalCheck {
  type: EvalCheckType;
  /** calls_tool, not_calls_tool */
  tool?: string;
  /** calls_tool */
  args?: ArgMatcher[];
  /** cites: knowledge base, and the document section when it matters. */
  source?: string;
  section?: string;
  /** reply_contains, reply_not_contains, refuses (the out-of-scope topic), rubric (the criterion). */
  text?: string;
  /** judge: what a good reply does. */
  rubric?: string;
  /** extracts */
  field?: string;
  value?: string;
}

/** `agent` is the owner's own test set; the rest are platform sets attached to every agent. */
export type EvalSuiteKind = 'agent' | 'injection' | 'leakage' | 'refusals';

export interface EvalCaseContext {
  /** Staff member or role the case runs as (run-as principal id); unset runs with the agent's own access. */
  runAsId?: string;
  runAsName?: string;
  /** Knowledge bases attached for this case. */
  collections: string[];
}

export type EvalCaseSource = 'manual' | 'csv' | 'test_turn' | 'platform';
export type EvalOutcome = 'pass' | 'fail';

export interface EvalCase {
  id: string;
  agentId: string;
  suite: EvalSuiteKind;
  name: string;
  input: string;
  context: EvalCaseContext;
  checks: EvalCheck[];
  source: EvalCaseSource;
  /** Platform cases cannot be edited or deleted by the agent's owner. */
  readOnly: boolean;
  createdAt: string;
  createdBy: string;
  /** Outcome on the newest version in the latest completed run; null when not run since it was added. */
  lastOutcome: EvalOutcome | null;
}

export interface EvalCaseInput {
  name: string;
  input: string;
  context: { runAsId?: string; collections: string[] };
  checks: EvalCheck[];
}

export type EvalCaseFilters = { suite?: string[]; source?: string[]; lastOutcome?: string[] };

export interface EvalSuite {
  kind: EvalSuiteKind;
  name: string;
  description: string;
  ownedBy: 'agent_owner' | 'platform';
  caseCount: number;
  /** On the newest version in the latest completed run. */
  passed: number | null;
  total: number | null;
  regressions: number | null;
}

/** Result of one check. `advisory` is a rubric check: recorded, never pass or fail. */
export interface EvalCheckResult {
  label: string;
  status: EvalOutcome | 'advisory';
  detail?: string;
}

export interface EvalCaseOutcome {
  status: EvalOutcome;
  checks: EvalCheckResult[];
  failure?: string;
  reply: string;
  latencyMs: number;
}

export interface EvalCaseResult {
  caseId: string;
  caseName: string;
  suite: EvalSuiteKind;
  draft: EvalCaseOutcome;
  live: EvalCaseOutcome | null;
  /** Passed on the compared version and fails on the newest one. */
  regression: boolean;
}

export interface EvalVersionStats {
  version: number;
  passed: number;
  total: number;
  costUsd: number;
  p95Ms: number;
}

export interface EvalSuiteSummary {
  kind: EvalSuiteKind;
  name: string;
  passed: number;
  total: number;
  regressions: number;
}

export interface EvalSummary {
  passed: number;
  total: number;
  regressions: number;
  /** Rubric checks recorded but not scored. */
  advisoryChecks: number;
  costUsd: number;
  p95Ms: number;
  draft: EvalVersionStats;
  live: EvalVersionStats | null;
  suites: EvalSuiteSummary[];
}

export type EvalRunStatus = 'running' | 'complete';
export type EvalRunTrigger = 'manual' | 'save' | 'restore';

export interface EvalRun {
  id: string;
  agentId: string;
  agentName: string;
  /** Newest saved version, the one being tested. */
  draftVersion: number;
  /** What it is compared with: the version live workflows use, or the previous one when the newest is already live. */
  compared: { version: number; label: 'live' | 'previous' } | null;
  trigger: EvalRunTrigger;
  status: EvalRunStatus;
  startedAt: string;
  finishedAt?: string;
  requestedBy: string;
  /** Null while running. */
  summary: EvalSummary | null;
  results: EvalCaseResult[];
}

export type EvalRunRow = Omit<EvalRun, 'results'>;
export type EvalRunFilters = { status?: string[]; trigger?: string[] };

