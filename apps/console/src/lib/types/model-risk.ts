import type { Risk, ValidationSummary } from './domain';
import type { EvalVersionSummary } from './evals';

/**
 * Model risk management: every agent and workflow is a model in the inventory, with a risk tier, independent
 * validation by Model Risk (the second line), conditions on its use, findings and monitoring.
 */

export type ModelType = 'agent' | 'workflow';
export type ValidationStatus = 'not_validated' | 'in_validation' | 'validated' | 'validated_with_conditions' | 'expired';

export interface ModelEntry {
  id: string;
  name: string;
  type: ModelType;
  /** The agent or workflow id. */
  refId: string;
  href: string;
  owner: string;
  ownerTeam: string;
  /** Resolved model, the AI gateway alias that serves it, and its provider. */
  model: string;
  alias: string;
  provider: string;
  tier: Risk;
  tierReason: string;
  validationStatus: ValidationStatus;
  /** yyyy-mm-dd; null when never validated. */
  nextReviewAt: string | null;
  openFindings: number;
  /** Latest eval pass rate, 0–1; null when no eval has run. */
  lastEvalPassRate: number | null;
  /** The open Model Risk review on this entry, if any: a new validation request is refused while it is open. */
  openReview: { id: string; scope: ValidationScope } | null;
}

export type ModelRiskView = 'all' | 'needs_validation' | 'due_30d' | 'open_findings' | 'expired';
export type ModelRiskFilters = { type?: string[]; tier?: string[]; validationStatus?: string[]; ownerTeam?: string[]; provider?: string[] };
export type ModelRiskViewCounts = Record<ModelRiskView, number>;

export interface ModelRiskStats {
  total: number;
  highOrCritical: number;
  notValidated: number;
  dueIn30d: number;
  openFindings: number;
}

export type ValidationOutcome = 'approved' | 'approved_with_conditions' | 'rejected';

export interface ValidationRecord {
  id: string;
  validator: string;
  date: string;
  outcome: ValidationOutcome;
  conditions: string[];
  reason?: string;
  reviewId?: string;
}

export type ConditionStatus = 'open' | 'met' | 'overdue';

export interface ModelCondition {
  id: string;
  text: string;
  owner: string;
  /** yyyy-mm-dd */
  dueDate: string;
  status: ConditionStatus;
  createdBy: string;
  createdAt: string;
}

export interface ConditionInput {
  text: string;
  owner: string;
  dueDate: string;
}

export type FindingSeverity = 'low' | 'medium' | 'high' | 'critical';
export type FindingStatus = 'open' | 'remediating' | 'closed';

export interface ModelFinding {
  id: string;
  title: string;
  severity: FindingSeverity;
  status: FindingStatus;
  raisedBy: string;
  raisedAt: string;
  dueDate?: string;
}

export interface EvidenceBundle {
  version: number;
  /** Sealed bundle id for that version. */
  bundleId: string;
  sealedAt: string;
}

export interface ModelEvidence {
  /** Agents: their latest eval. Workflows: the latest eval of each pinned agent. */
  evals: { name: string; version: number; summary: EvalVersionSummary }[];
  /** Workflows only: the latest workflow test run. */
  workflowSuite: (ValidationSummary & { ranAt: string }) | null;
  bundles: EvidenceBundle[];
}

export interface ModelMonitoring {
  passRateByVersion: { version: string; passRate: number }[];
  /** Share of reviewed actions where the approver changed or rejected the proposal, per day. */
  overrideRate30d: { date: string; rate: number }[];
}

export interface ModelEntryDetail extends ModelEntry {
  purpose: string;
  dataTouched: string[];
  systems: string[];
  knowledgeBases: string[];
  evidence: ModelEvidence;
  validations: ValidationRecord[];
  conditions: ModelCondition[];
  findings: ModelFinding[];
  monitoring: ModelMonitoring;
  /** The open second-line review for this entry (validation or tier change), if any. */
  pendingReview?: { id: string; scope: ValidationScope; toTier?: Risk };
}

export interface TierChangeInput {
  tier: Risk;
  reason: string;
}

export type ValidationScope = 'initial' | 'periodic' | 'tier_change';

/** Body of a `model_validation` review in the Reviews queue. */
export interface ModelValidationRequest {
  entryId: string;
  entryName: string;
  entryType: ModelType;
  scope: ValidationScope;
  tier: Risk;
  /** Tier changes only. */
  fromTier?: Risk;
  toTier?: Risk;
  requestedBy: string;
  note: string;
  evidence: string[];
  /** Set once decided. */
  outcome?: ValidationOutcome;
  conditions?: ConditionInput[];
}

/** The workflow's inventory entry as a publish request shows it. */
export interface PublishModelEntry {
  entryId: string;
  tier: Risk;
  validationStatus: ValidationStatus;
  /** Medium or above and not validated: shown to the approver. */
  needsValidation: boolean;
}

export interface ModelRiskOptions {
  owners: string[];
  validators: string[];
}
