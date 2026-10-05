import type { Risk } from '@/lib/types/domain';
import type { FindingSeverity, FindingStatus, ValidationOutcome, ValidationStatus } from '@/lib/types/model-risk';

/**
 * Inventory seeds keyed by agent or workflow id. Dates are offsets in days from today so the "due in 30 days"
 * and "expired" views always have rows.
 */
export interface EntrySeed {
  tier: Risk;
  tierReason: string;
  status: Exclude<ValidationStatus, 'in_validation' | 'expired'>;
  /** Days from today; negative is past (an expired validation). */
  nextReviewInDays?: number;
  purpose?: string;
  dataTouched: string[];
  validations: { validator: string; daysAgo: number; outcome: ValidationOutcome; conditions?: string[]; reason?: string }[];
  conditions: { text: string; owner: string; dueInDays: number; status?: 'open' | 'met' }[];
  findings: { title: string; severity: FindingSeverity; status: FindingStatus; raisedBy: string; daysAgo: number; dueInDays?: number }[];
}

export const ENTRY_SEEDS: Record<string, EntrySeed> = {
  wf_wire: {
    tier: 'critical',
    tierReason: 'Places holds on customer wires (money movement) on every outbound wire of $10,000 or more.',
    status: 'validated_with_conditions',
    nextReviewInDays: 21,
    dataTouched: ['Wire instructions', 'Payee details', 'MFA results', 'Account history'],
    validations: [
      { validator: 'Priya Shah', daysAgo: 160, outcome: 'approved_with_conditions', conditions: ['Human approval on all writes until 2026-12-31'] },
      { validator: 'Priya Shah', daysAgo: 400, outcome: 'approved' },
    ],
    conditions: [
      { text: 'Human approval on all writes until 2026-12-31', owner: 'Fraud Strategy', dueInDays: 88 },
      { text: 'Monthly sample of 50 released holds reviewed by Fraud QA', owner: 'Fraud Strategy', dueInDays: 12, status: 'met' },
    ],
    findings: [{ title: 'Injection regressions on Wire Fraud Sentinel v7 not yet remediated', severity: 'high', status: 'open', raisedBy: 'Priya Shah', daysAgo: 2, dueInDays: 14 }],
  },
  wf_mortgage: {
    tier: 'high',
    tierReason: 'Issues pre-approvals that customers rely on; decisions use credit bureau data.',
    status: 'validated',
    nextReviewInDays: 140,
    dataTouched: ['Credit bureau reports', 'Employment and income', 'Application documents'],
    validations: [{ validator: 'Priya Shah', daysAgo: 225, outcome: 'approved' }],
    conditions: [],
    findings: [{ title: 'Fair-lending disparity test not run on Q3 decisions', severity: 'medium', status: 'remediating', raisedBy: 'Daniel Brooks', daysAgo: 30, dueInDays: 25 }],
  },
  wf_dispute: {
    tier: 'high',
    tierReason: 'Posts provisional credit to card accounts (money movement).',
    status: 'not_validated',
    dataTouched: ['Card transactions', 'Dispute narratives', 'Merchant data'],
    validations: [],
    conditions: [],
    findings: [],
  },
  wf_kyb: {
    tier: 'medium',
    tierReason: 'Recommends account opening decisions; a person approves every watchlist hit.',
    status: 'validated',
    nextReviewInDays: -9,
    dataTouched: ['Government ID', 'Corporate registry', 'Watchlist results'],
    validations: [{ validator: 'Priya Shah', daysAgo: 374, outcome: 'approved' }],
    conditions: [],
    findings: [],
  },
  wf_branch_chat: {
    tier: 'low',
    tierReason: 'Answers product questions from public knowledge and books appointments; no account access.',
    status: 'validated',
    nextReviewInDays: 260,
    dataTouched: ['Product knowledge', 'Branch schedules'],
    validations: [{ validator: 'Anika Singh', daysAgo: 105, outcome: 'approved' }],
    conditions: [],
    findings: [],
  },
  wf_card_inbox: {
    tier: 'medium',
    tierReason: 'Drafts card actions from customer email; every write needs an approver.',
    status: 'not_validated',
    dataTouched: ['Customer email', 'Card transactions', 'Attachments'],
    validations: [],
    conditions: [],
    findings: [{ title: 'Attachment parsing not covered by the test suite', severity: 'medium', status: 'open', raisedBy: 'Anika Singh', daysAgo: 6, dueInDays: 30 }],
  },
  wf_lending_inbox: {
    tier: 'medium',
    tierReason: 'Drafts hardship and payoff actions from email; writes need approval.',
    status: 'validated_with_conditions',
    nextReviewInDays: 27,
    dataTouched: ['Customer email', 'Loan balances', 'Hardship details'],
    validations: [{ validator: 'Priya Shah', daysAgo: 338, outcome: 'approved_with_conditions', conditions: ['Hardship replies reviewed by a person until the suite has 30 cases'] }],
    conditions: [{ text: 'Hardship replies reviewed by a person until the suite has 30 cases', owner: 'Lending Ops', dueInDays: -4 }],
    findings: [],
  },
  wf_advisor: {
    tier: 'medium',
    tierReason: 'Drafts client-facing portfolio notes that an advisor signs.',
    status: 'not_validated',
    dataTouched: ['Portfolio holdings', 'Client profile'],
    validations: [],
    conditions: [],
    findings: [],
  },
  ag_fraud: {
    tier: 'high',
    tierReason: 'Calls place_wire_hold (money movement).',
    status: 'validated',
    nextReviewInDays: 45,
    dataTouched: ['Wire history', 'Fraud playbook'],
    validations: [{ validator: 'Priya Shah', daysAgo: 160, outcome: 'approved' }],
    conditions: [],
    findings: [],
  },
  ag_loan: {
    tier: 'high',
    tierReason: 'Calls issue_preapproval (write) and reads credit reports.',
    status: 'validated',
    nextReviewInDays: 140,
    dataTouched: ['Credit reports', 'Employment records'],
    validations: [{ validator: 'Priya Shah', daysAgo: 225, outcome: 'approved' }],
    conditions: [],
    findings: [],
  },
  ag_kyb: { tier: 'medium', tierReason: 'Read-only screening tools; recommends, never decides.', status: 'validated', nextReviewInDays: 18, dataTouched: ['Watchlists', 'Corporate registry'], validations: [{ validator: 'Anika Singh', daysAgo: 347, outcome: 'approved' }], conditions: [], findings: [] },
  ag_dispute: { tier: 'medium', tierReason: 'Proposes provisional credit; the workflow gate approves it.', status: 'not_validated', dataTouched: ['Card transactions'], validations: [], conditions: [], findings: [] },
  ag_branch: { tier: 'low', tierReason: 'Public product knowledge and appointment booking only.', status: 'validated', nextReviewInDays: 260, dataTouched: ['Product knowledge'], validations: [{ validator: 'Anika Singh', daysAgo: 105, outcome: 'approved' }], conditions: [], findings: [] },
  ag_advisor: { tier: 'medium', tierReason: 'Client-facing drafts; no tools yet.', status: 'not_validated', dataTouched: ['Portfolio holdings'], validations: [], conditions: [], findings: [] },
};

/** Open second-line reviews raised by other people, so the current user (acting as Model Risk) can decide them. */
export const VALIDATION_SEEDS: { refId: string; scope: 'initial' | 'periodic' | 'tier_change'; toTier?: Risk; by: string; note: string; minutesAgo: number }[] = [
  { refId: 'wf_wire', scope: 'periodic', by: 'Maya Okafor', note: 'Annual revalidation; the hold condition expires 2026-12-31.', minutesAgo: 60 * 26 },
  { refId: 'wf_card_inbox', scope: 'initial', by: 'Maya Okafor', note: 'First validation before the inbox handles disputes over $1,500.', minutesAgo: 60 * 5 },
  { refId: 'wf_kyb', scope: 'tier_change', toTier: 'high', by: 'Daniel Brooks', note: 'Adding corporate account opening without a person for low-risk owners.', minutesAgo: 140 },
];

export const VALIDATORS = ['James Richardson', 'Priya Shah', 'Anika Singh'];
