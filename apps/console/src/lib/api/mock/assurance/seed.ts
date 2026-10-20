import type { AssuranceRunTrigger, CaseOutcome } from '@/lib/types/assurance';

/**
 * Seed for the two Assurance concepts no other store holds: LLM judges with their calibration against reviewer
 * labels, and eval runs started by a model update or a knowledge change. Everything else on the page is
 * computed from the evals, skills, workflow test, model risk and review stores.
 */

export interface JudgeSeed {
  id: string;
  name: string;
  criterion: string;
  model: string;
  promptVersion: number;
  calibrationSize: number;
  agreement: number;
  recalibratedDaysAgo: number;
  disagreements: { caseName: string; assetName: string; judge: CaseOutcome; human: CaseOutcome; reviewer: string; note: string }[];
}

export const MIN_AGREEMENT = 0.7;

export const JUDGES: JudgeSeed[] = [
  {
    id: 'jdg_grounded',
    name: 'Grounded answer',
    criterion: 'Every factual claim is supported by a cited passage',
    model: 'claude-sonnet-5',
    promptVersion: 4,
    calibrationSize: 120,
    agreement: 0.86,
    recalibratedDaysAgo: 12,
    disagreements: [
      { caseName: 'Chargeback window for recurring billing', assetName: 'Card Dispute Resolver', judge: 'pass', human: 'fail', reviewer: 'Maya Okafor', note: 'Cited the right guide but quoted the 2025 window.' },
      { caseName: 'Foreign wire limit question', assetName: 'Wire Fraud Sentinel', judge: 'fail', human: 'pass', reviewer: 'Daniel Brooks', note: 'Claim is in the playbook appendix, which the judge did not count as cited.' },
    ],
  },
  {
    id: 'jdg_tone',
    name: 'Plain-language tone',
    criterion: 'Reply follows the bank tone guide: plain, warm, specific',
    model: 'claude-haiku-4-5',
    promptVersion: 2,
    calibrationSize: 64,
    agreement: 0.62,
    recalibratedDaysAgo: 41,
    disagreements: [
      { caseName: 'Hardship deferral reply', assetName: 'Mortgage Intake', judge: 'pass', human: 'fail', reviewer: 'Anika Singh', note: 'Warm, but promises an outcome before underwriting.' },
      { caseName: 'Branch hours on a holiday', assetName: 'Branch Concierge', judge: 'fail', human: 'pass', reviewer: 'Priya Shah', note: 'Short reply is correct for a simple question.' },
      { caseName: 'Declined card follow-up', assetName: 'Card Dispute Resolver', judge: 'pass', human: 'fail', reviewer: 'Maya Okafor', note: 'Uses internal reason-code wording.' },
    ],
  },
  {
    id: 'jdg_disclosure',
    name: 'Required disclosure',
    criterion: 'Customer-facing drafts carry the disclosure their product needs',
    model: 'claude-sonnet-5',
    promptVersion: 3,
    calibrationSize: 88,
    agreement: 0.91,
    recalibratedDaysAgo: 6,
    disagreements: [{ caseName: 'Collections outreach, first notice', assetName: 'Lending servicing inbox', judge: 'fail', human: 'pass', reviewer: 'James Richardson', note: 'Provincial wording variant is accepted by Compliance.' }],
  },
];

export interface ExtraRunSeed {
  agentId: string;
  trigger: Extract<AssuranceRunTrigger, 'model_update' | 'knowledge_change'>;
  daysAgo: number;
  passed: number;
  total: number;
  regressions: number;
  durationMs: number;
  costUsd: number;
}

export const EXTRA_RUNS: ExtraRunSeed[] = [
  { agentId: 'ag_fraud', trigger: 'model_update', daysAgo: 3, passed: 21, total: 22, regressions: 1, durationMs: 214_000, costUsd: 0.53 },
  { agentId: 'ag_loan', trigger: 'model_update', daysAgo: 3, passed: 19, total: 19, regressions: 0, durationMs: 188_000, costUsd: 0.46 },
  { agentId: 'ag_dispute', trigger: 'knowledge_change', daysAgo: 1, passed: 16, total: 18, regressions: 2, durationMs: 151_000, costUsd: 0.41 },
  { agentId: 'ag_branch', trigger: 'knowledge_change', daysAgo: 2, passed: 17, total: 17, regressions: 0, durationMs: 97_000, costUsd: 0.08 },
];
