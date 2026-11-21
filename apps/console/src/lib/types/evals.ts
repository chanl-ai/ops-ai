import type { Risk } from './domain';

/**
 * Agent evals as agents-service keeps them: saved cases, and kept runs that happen when someone presses Run evals or
 * runs `opsai agents eval`. A check is one of the four the service scores; a judge check asks a model to grade the
 * reply against its rubric, and the run's cost includes that grading.
 */

export type EvalCheckType = 'calls_tool' | 'reply_contains' | 'refuses' | 'judge';

/** One expectation on a case. Only the field its `type` needs is set. */
export interface EvalCheck {
  type: EvalCheckType;
  /** calls_tool */
  tool?: string;
  /** reply_contains; refuses (the out-of-scope topic) */
  text?: string;
  /** judge: what a good reply does. */
  rubric?: string;
}

export interface EvalCase {
  id: string;
  name: string;
  input: string;
  checks: EvalCheck[];
  /** Knowledge bases attached for this case. */
  collections: string[];
  /** `active` cases run; `draft` ones were proposed from a review and wait for a person. */
  status: string;
  source: string;
  createdAt: string;
  createdBy: string;
}

export interface EvalCaseInput {
  name: string;
  input: string;
  collections: string[];
  checks: EvalCheck[];
}

/** Result of one check; a judge check also carries the judge's reason and confidence. */
export interface EvalCheckResult {
  label: string;
  status: 'pass' | 'fail';
  reason?: string | null;
  confidence?: number | null;
}

export interface EvalCaseOutcome {
  status: 'pass' | 'fail';
  checks: EvalCheckResult[];
  reply: string;
  latencyMs: number;
}

export interface EvalCaseResult {
  caseName: string;
  draft: EvalCaseOutcome;
  live: EvalCaseOutcome | null;
  /** Passed on the live version and fails on the newest one. */
  regression: boolean;
  /** The judge's model has no price, so this case's cost is missing from the run's. */
  unpriced: boolean;
}

export interface EvalSummary {
  passed: number;
  total: number;
  regressions: number;
}

/** A kept run: the newest version, and the live one it was compared with when that is another. */
export interface EvalRun {
  id: string;
  agentId: string;
  version: number;
  liveVersion: number | null;
  /** `manual`, or `publish_request` when a publish check started it. */
  trigger: string;
  /** The service runs synchronously: a kept run is always complete. */
  status: 'complete';
  summary: EvalSummary;
  results: EvalCaseResult[];
  costUsd: number;
  /** A model in the run has no price: the cost is a lower bound. */
  unpriced: boolean;
  startedBy: string;
  ranAt: string;
}

/** Eval result shown against one agent version (version history, publish requests). */
export interface EvalVersionSummary {
  runId: string;
  ranAt: string;
  passed: number;
  total: number;
  regressions: number;
  injection: { passed: number; total: number; regressions: number };
}

/** One agent pinned by a publish request, with the eval result for the version being pinned. */
export interface AgentEvalPin {
  agentId: string;
  agentName: string;
  version: number;
  summary: EvalVersionSummary | null;
  /** Set when this agent blocks the publish. */
  blocker?: string;
  /** Why it blocks, so the approver's message names the real cause. */
  blockerKind?: 'running' | 'no_run' | 'injection' | 'failing';
  /** Non-blocking failures the approver must explain. */
  advisory: string[];
}

/** The eval part of a publish request's gate (spec 04, S4 blocking and S5/S6 advisory). */
export interface EvalGate {
  tier: Risk;
  /** Injection pass rate the tier requires, 0–1. */
  injectionThreshold: number;
  blockers: string[];
  advisory: string[];
  /** Approving needs a written reason because advisory failures exist. */
  reasonRequired: boolean;
}
