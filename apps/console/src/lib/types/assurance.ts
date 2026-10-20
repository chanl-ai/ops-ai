import type { Risk } from './domain';
import type { ListResult } from './query';

/**
 * Assurance: suites, eval runs, publish gates, sealed evidence and LLM judges for every asset that can change
 * production, read through one API (spec 04). Counts and rates are computed by the API.
 */

export type AssetKind = 'agent' | 'skill' | 'workflow';

export interface AssetRef {
  kind: AssetKind;
  id: string;
  name: string;
  href: string;
}

export type CaseOutcome = 'pass' | 'fail';

/** One case in a suite's latest run: the candidate version against the live one, with a reviewer's label when one exists. */
export interface SuiteCaseResult {
  caseId: string;
  name: string;
  candidate: CaseOutcome;
  live: CaseOutcome | null;
  regression: boolean;
  /** The outcome a reviewer recorded for this case; null when nobody has labelled it. */
  humanVerdict: CaseOutcome | null;
}

/** A case proposed from a review decision. Draft cases are not run by the gate until the owner activates them. */
export interface SuiteDraftCase {
  id: string;
  name: string;
  input: string;
  source: 'review';
  status: 'draft';
  reviewId: string;
  reason: string;
  createdBy: string;
  createdAt: string;
}

export interface AssuranceSuite {
  /** `${kind}:${assetId}` */
  id: string;
  asset: AssetRef;
  owner: string;
  tier: Risk;
  /** Active cases. */
  cases: number;
  draftCases: number;
  /** On the candidate version in the latest run, 0–1; null when it has never run. */
  passRate: number | null;
  /** The same cases on the live version, 0–1; null when nothing is live or it was not compared. */
  livePassRate: number | null;
  regressions: number | null;
  candidateVersion: number | null;
  liveVersion: number | null;
  lastRunAt: string | null;
  failing: boolean;
  results: SuiteCaseResult[];
  drafts: SuiteDraftCase[];
}

export type AssuranceRunTrigger = 'publish_request' | 'model_update' | 'manual' | 'knowledge_change' | 'version_saved';

export interface AssuranceRun {
  id: string;
  asset: AssetRef;
  version: number;
  trigger: AssuranceRunTrigger;
  passed: number;
  total: number;
  /** 0–1 */
  passRate: number;
  regressions: number;
  durationMs: number;
  costUsd: number;
  ranAt: string;
  /** The review this run fed, when it gated a publish. */
  reviewId?: string;
}

export type GateStepId = 'structural' | 'evidence_integrity' | 'injection' | 'pass_rate' | 'regressions';
export type GateStepResult = 'pass' | 'fail' | 'pending';

export interface GateStep {
  step: GateStepId;
  label: string;
  /** Set by the risk tier: blocking failures stop the publish, advisory ones need the approver's reason. */
  mode: 'blocking' | 'advisory';
  result: GateStepResult;
  detail: string;
}

export interface AssuranceGate {
  reviewId: string;
  asset: AssetRef;
  /** Null on a first publish. */
  fromVersion: number | null;
  toVersion: number;
  tier: Risk;
  requestedBy: string;
  requestedAt: string;
  reviewStatus: 'pending' | 'in_review' | 'approved' | 'rejected' | 'returned';
  steps: GateStep[];
  /** Open with a failing blocking step. */
  blocked: boolean;
}

export interface EvidenceBundleRow {
  id: string;
  asset: AssetRef;
  version: number;
  digest: string;
  approvers: string[];
  sealedAt: string;
  /** The version is what production runs now. */
  live: boolean;
}

export interface JudgeDisagreement {
  id: string;
  caseName: string;
  assetName: string;
  criterion: string;
  judge: CaseOutcome;
  human: CaseOutcome;
  reviewer: string;
  note: string;
}

export interface AssuranceJudge {
  id: string;
  name: string;
  criterion: string;
  model: string;
  promptVersion: number;
  calibrationSize: number;
  /** Agreement with reviewer labels on the calibration set (Cohen's kappa), 0–1. */
  agreement: number;
  /** Below this, the judge's verdicts are advisory at every tier. */
  minAgreement: number;
  lastRecalibratedAt: string;
  disagreements: JudgeDisagreement[];
}

export interface AssuranceStats {
  failingSuites: number;
  gatesBlocked: number;
  liveUnsealed: number;
  lowestJudge: { name: string; agreement: number } | null;
}

export type AssuranceTab = 'suites' | 'runs' | 'gates' | 'evidence' | 'judges';
export interface AssuranceRowOf {
  suites: AssuranceSuite;
  runs: AssuranceRun;
  gates: AssuranceGate;
  evidence: EvidenceBundleRow;
  judges: AssuranceJudge;
}
export type AssuranceRow = AssuranceRowOf[AssuranceTab];

export type AssuranceFilters = { kind?: string[]; tier?: string[]; trigger?: string[]; result?: string[] };

export interface AssuranceResult<T extends AssuranceRow = AssuranceRow> extends ListResult<T> {
  stats: AssuranceStats;
  tabCounts: Record<AssuranceTab, number>;
}
