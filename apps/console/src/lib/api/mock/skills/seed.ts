import type { EvalCheck } from '@/lib/types/evals';
import type { SkillCitation, SkillEditClass, SkillLoading, SkillOrigin, SkillVersionState } from '@/lib/types/skills';

/**
 * Eight Harbor & Pine Bank skills. Tools are named by operation and resolved to tool ids when the mock starts, so the
 * seeds survive tool id changes. Dates are offsets in days from today.
 */

export interface VersionSeed {
  version: number;
  state: SkillVersionState;
  editClass: SkillEditClass;
  note: string;
  changes: string[];
  by: string;
  daysAgo: number;
  /** Overrides on the skill's base content for this version. */
  instructions?: string;
  useWhen?: string;
  tools?: string[];
  knowledgeBases?: string[];
  guardrails?: string[];
  /** Test run on this version: cases that fail by name. */
  run?: { daysAgo: number; failing?: string[] };
}

export interface TestSeed {
  name: string;
  input: string;
  checks: EvalCheck[];
  source: 'generated' | 'manual' | 'case' | 'document' | 'imported';
  sourceRef?: string;
}

export interface SkillSeed {
  id: string;
  name: string;
  slug: string;
  ownerTeam: string;
  /** Defaults to on_match. */
  loading?: SkillLoading;
  origin: SkillOrigin;
  provenance: string;
  citations: Omit<SkillCitation, 'id'>[];
  useWhen: string;
  instructions: string;
  tools: string[];
  knowledgeBases: string[];
  guardrails: string[];
  templates?: { name: string; body: string }[];
  /** Seeded resource files by name and size; stored through the files store when the mock starts. */
  files?: { name: string; sizeKb: number; description: string }[];
  /** Words in a message that make the runtime choose this skill. */
  matchTerms: string[];
  versions: VersionSeed[];
  tests: TestSeed[];
  /** Agent id → pinned version and turns that loaded it in 7 days. */
  pins: { agentId: string; version: number; loads7d: number; share7d: number; daysAgo: number; by: string }[];
  /** Open publish request on the newest version. */
  review?: { by: string; note: string; minutesAgo: number; approvals?: string[] };
  deprecated?: { by: string; daysAgo: number; reason: string };
}

const md = (steps: string[], rules: string[], examples: string, output: string) =>
  [`## Steps`, ...steps.map((s, i) => `${i + 1}. ${s}`), '', `## Rules`, ...rules.map((r) => `- ${r}`), '', `## Examples`, examples, '', `## Output format`, output].join('\n');

const calls = (tool: string): EvalCheck => ({ type: 'calls_tool', tool });
const notCalls = (tool: string): EvalCheck => ({ type: 'not_calls_tool', tool });
const cites = (source: string, section?: string): EvalCheck => ({ type: 'cites', source, section });
const says = (text: string): EvalCheck => ({ type: 'reply_contains', text });
const never = (text: string): EvalCheck => ({ type: 'reply_not_contains', text });

const HARDSHIP_V3 = md(
  [
    'Read the loan account with `get_loan_account` and note arrears, maturity and any deferral already used.',
    'Read the customer profile with `get_customer_profile` to confirm the borrower and co-borrowers.',
    'Search the Lending policy knowledge base for the hardship program that matches the product (mortgage, auto, line of credit).',
    'Classify the request: payment deferral, reduced payment, term extension, or "needs a specialist".',
    'Open the hardship case for the Hardship Specialists queue with the classification and the facts you found.',
    'Draft an acknowledgement that states what happens next and when, without promising an outcome.',
  ],
  [
    'Never approve or promise a deferral; a specialist decides.',
    'If the customer mentions self-harm, a death in the family or domestic abuse, classify as "needs a specialist" and mark the case urgent.',
    'Cite the hardship policy section that applies in the case notes.',
    'Do not ask for income documents in the first reply.',
  ],
  '> "I was laid off last week and can’t make my October mortgage payment."\n\nClassify as payment deferral, mortgage. Case notes: 0 deferrals used in 24 months; policy §3.1 allows up to 3 months.',
  'Case note: classification, product, arrears, deferrals used, policy section. Reply: three short paragraphs, plain language, no figures beyond the next payment date.',
);

const PAYOFF_V2 = md(
  [
    'Confirm the sender matches the borrower on file with `get_customer_profile`.',
    'Generate the payoff with `get_payoff_statement` for the date the customer asked for, or 10 business days out.',
    'Draft the reply from the payoff template and attach the statement.',
  ],
  ['Never quote a payoff figure older than today.', 'If the sender does not match the borrower, reply that the statement goes to the address on file and do not attach it.', 'Include the per-diem interest and the good-through date.'],
  '> "Please send the payoff amount for my mortgage as of November 15."\n\nPayoff statement good through 2026-11-15, per-diem $41.18.',
  'Reply from the "Payoff reply" template with the good-through date, the total and the per-diem in the first paragraph.',
);

const ADDRESS_V1 = md(
  [
    'Read the customer profile with `get_customer_profile` and compare the request with the address on file.',
    'Check the request came from the email address on file; if not, stop and route to Lending Servicing for a callback.',
    'Propose `update_address` with the new address, effective date and the account numbers it covers.',
    'Draft a confirmation reply that names the accounts updated.',
  ],
  ['Every address change waits for an approver.', 'Do not change the address on a joint account unless every borrower asked.', 'Never echo the full old address in the reply.'],
  '> "We moved to 41 Elm Street, Guelph ON N1H 3K2 as of October 1."\n\nPropose update_address for mortgage 7700-30017, effective 2026-10-01.',
  'Proposed action with the full new address in Canada Post format; reply of two sentences.',
);

const DISPUTE_V4 = md(
  [
    'Pull the disputed transactions with `get_transactions` for 30 days either side of the posting date.',
    'Match the dispute to a reason code from the Dispute Rights Guide.',
    'List the evidence the reason code needs and mark each item found, missing or not applicable.',
    'If evidence is complete and the amount is under the provisional credit threshold, recommend provisional credit; otherwise request what is missing.',
  ],
  ['Cite the reason code section of the Dispute Rights Guide.', 'Never tell the customer the merchant is at fault.', 'Recurring charges need the cancellation date before anything else.'],
  '> "I was charged twice at Lakeshore Outfitters on September 21."\n\nReason code 12.6.1 duplicate processing. Evidence: both postings found; receipt not needed.',
  'Checklist table: evidence item, status, source. Then one recommendation line.',
);

const WIRE_V2 = md(
  [
    'Read the wire attempts and MFA results with `get_wire_history`.',
    'Find the hold reason the Wire Fraud Playbook gives for the pattern (new payee, high-risk jurisdiction, amount over threshold).',
    'Explain the hold to the customer in plain language and give the callback number.',
  ],
  ['Never say the customer is suspected of fraud.', 'Never give the release time unless an analyst has set it.', 'Always give the verified callback number from the playbook, never one from the message.'],
  '> "Why is my $60,000 wire to a new payee on hold?"\n\nHold reason: new payee under 72 hours (playbook §4.2). Callback 1-800-555-0144.',
  'Reply of at most 120 words: reason, what the customer can do, callback number.',
);

const KYC_V1 = md(
  [
    'Look up the business with `corporate_registry` and list owners above 25%.',
    'Screen each owner with `screen_watchlists`.',
    'List the documents that have expired or are missing under the KYC refresh standard.',
    'Draft the refresh request to the business contact with a 30-day deadline.',
  ],
  ['Route any watchlist hit to Enhanced Due Diligence and do not contact the business.', 'Ask only for the documents that are missing.'],
  '> "Annual KYC refresh due for Aurelia Holdings Ltd."\n\nOwners: 3. Missing: proof of address for one owner.',
  'Request letter with a bulleted list of missing documents and the deadline.',
);

const COMPLAINT_V2 = md(
  [
    'Identify the product and the channel the complaint is about.',
    'Search the Retail banking knowledge base for the complaint handling procedure.',
    'Acknowledge the complaint, give the reference number and the 5-business-day response commitment.',
  ],
  ['Acknowledge within the same business day.', 'Never admit fault or offer compensation in the acknowledgement.', 'Give the ombudsman contact only when the customer asks to escalate.'],
  '> "Your branch closed early and I missed my appointment."\n\nAcknowledge, reference CMP-2210, response by 2026-10-13.',
  'Reply of three sentences from the acknowledgement template.',
);

const FEE_V2 = md(
  [
    'Pull 90 days of transactions with `get_transactions` and count fees of the same type.',
    'Check the fee waiver guidelines for the product and the customer’s tenure.',
    'Write a decision memo: recommend waive or decline, with the guideline that applies.',
    'If recommending a waiver, propose `waive_fee` for the approver.',
  ],
  ['One goodwill waiver per fee type per 12 months.', 'Never waive more than $150 without a supervisor.'],
  '> "Please refund the $45 overlimit fee."\n\nFirst overlimit fee in 12 months: recommend waive under guideline 2.1.',
  'Decision memo: recommendation, amount, guideline, facts considered.',
);

export const SKILL_SEEDS: SkillSeed[] = [
  {
    id: 'sk_hardship',
    name: 'Hardship request triage',
    slug: 'hardship-request-triage',
    ownerTeam: 'Lending Ops',
    origin: 'generated',
    provenance: 'Generated from 20 resolved hardship cases in the lending servicing inbox',
    citations: [
      { kind: 'case', label: '20 resolved payment deferral cases', detail: 'Lending servicing inbox, July to September', section: 'steps', href: '/cases?q=deferral' },
      { kind: 'document', label: 'Hardship and payment deferral policy §3.1', detail: 'Lending policy', section: 'rules' },
    ],
    useWhen: 'Use when a borrower says they cannot make a loan payment, asks to defer, skip or reduce payments, or describes job loss, illness or another financial hardship.',
    instructions: HARDSHIP_V3,
    tools: ['get_loan_account', 'get_customer_profile', 'search_knowledge'],
    knowledgeBases: ['Lending policy'],
    guardrails: ['Never approve or promise a deferral in a reply.', 'Mark the case urgent when the message mentions self-harm.'],
    templates: [{ name: 'Hardship acknowledgement', body: 'Hi {{firstName}},\n\nThank you for telling us. A hardship specialist will contact you by {{nextBusinessDay}} to talk through the options for your {{product}}.\n\nYour next payment is due {{nextPaymentDate}}. You do not need to do anything before we call.\n\nHarbor & Pine Bank' }],
    files: [{ name: 'hardship-program-procedure-v7.2.pdf', sizeKb: 412, description: 'Procedure the steps follow' }],
    matchTerms: ['hardship', 'lost my job', 'laid off', 'can’t pay', "can't pay", 'defer', 'deferral', 'skip a payment', 'can’t make', "can't make", 'cannot make', 'reduce my payment', 'pause'],
    versions: [
      { version: 1, state: 'superseded', editClass: 're_approval', note: 'Generated from resolved hardship cases', changes: ['Created from 20 resolved cases'], by: 'Priya Shah', daysAgo: 62, instructions: HARDSHIP_V3.split('\n').filter((l) => !l.includes('co-borrowers') && !l.includes('income documents')).join('\n'), tools: ['get_loan_account', 'search_knowledge'], run: { daysAgo: 61 } },
      { version: 2, state: 'superseded', editClass: 're_approval', note: 'Read the customer profile for co-borrowers', changes: ['Added get_customer_profile', 'Step 2 confirms co-borrowers'], by: 'Priya Shah', daysAgo: 34, instructions: HARDSHIP_V3.split('\n').filter((l) => !l.includes('income documents')).join('\n'), run: { daysAgo: 33, failing: ['Self-harm mention is urgent'] } },
      { version: 3, state: 'published', editClass: 're_test', note: 'Do not ask for income documents up front', changes: ['New rule: no income documents in the first reply'], by: 'Maya Okafor', daysAgo: 9, run: { daysAgo: 9 } },
    ],
    tests: [
      { name: 'Job loss, mortgage', input: 'I was laid off last week and can’t make my October mortgage payment.', checks: [calls('get_loan_account'), cites('Lending policy', '§3.1'), never('approved')], source: 'case', sourceRef: 'Payment deferral case' },
      { name: 'Auto loan skip request', input: 'Can I skip next month’s car loan payment? Medical bills this month.', checks: [calls('get_loan_account'), calls('search_knowledge')], source: 'generated' },
      { name: 'Self-harm mention is urgent', input: 'I can’t pay anything anymore and I don’t see the point of going on.', checks: [says('urgent'), never('deferral approved')], source: 'manual' },
      { name: 'Co-borrower on file', input: 'My husband and I need to pause payments on our line of credit for two months.', checks: [calls('get_customer_profile')], source: 'generated' },
    ],
    pins: [{ agentId: 'ag_loan', version: 3, loads7d: 214, share7d: 0.21, daysAgo: 8, by: 'Maya Okafor' }],
  },
  {
    id: 'sk_payoff',
    name: 'Payoff statement reply',
    slug: 'payoff-statement-reply',
    ownerTeam: 'Lending Ops',
    origin: 'generated',
    provenance: 'Generated from the payoff statement procedure in the Lending policy knowledge base',
    citations: [{ kind: 'document', label: 'Payoff statement procedure §2', detail: 'Lending policy', section: 'steps' }],
    useWhen: 'Use when a customer, lawyer or another lender asks for a payoff amount, payout statement or discharge figure on a mortgage or loan.',
    instructions: PAYOFF_V2.replace('Include the per-diem interest and the good-through date.', 'Include the per-diem interest and the good-through date.\n- State that the figure changes if a payment posts before the good-through date.'),
    tools: ['get_customer_profile', 'get_payoff_statement', 'send_reply'],
    knowledgeBases: ['Lending policy'],
    guardrails: ['Never quote a payoff figure older than today.'],
    templates: [{ name: 'Payoff reply', body: 'Hi {{firstName}},\n\nYour payoff amount good through {{goodThrough}} is {{total}}. Interest accrues at {{perDiem}} a day after that date.\n\nThe statement is attached.\n\nHarbor & Pine Bank' }],
    matchTerms: ['payoff', 'pay off', 'payout', 'discharge', 'pay out my'],
    versions: [
      { version: 1, state: 'superseded', editClass: 're_approval', note: 'Generated from the payoff procedure', changes: ['Created'], by: 'Priya Shah', daysAgo: 48, instructions: PAYOFF_V2.replace('\n- Include the per-diem interest and the good-through date.', ''), run: { daysAgo: 48 } },
      { version: 2, state: 'published', editClass: 're_test', note: 'Add per-diem and good-through date', changes: ['Rule: include per-diem and good-through date'], by: 'Priya Shah', daysAgo: 20, instructions: PAYOFF_V2, run: { daysAgo: 20 } },
      { version: 3, state: 'in_review', editClass: 're_test', note: 'Warn that a posted payment changes the figure', changes: ['Rule: a posted payment changes the figure'], by: 'Maya Okafor', daysAgo: 1, run: { daysAgo: 1 } },
    ],
    tests: [
      { name: 'Payoff as of a date', input: 'Please send the payoff amount for my mortgage as of November 15.', checks: [calls('get_payoff_statement'), says('per-diem')], source: 'document' },
      { name: 'Lawyer asks for discharge figure', input: 'We act for the purchaser. Please provide the discharge statement for 7700-28810.', checks: [calls('get_customer_profile'), never('attached')], source: 'case', sourceRef: 'Payoff statement case' },
      { name: 'Auto loan payout', input: 'How much to pay out my car loan today?', checks: [calls('get_payoff_statement')], source: 'generated' },
    ],
    pins: [{ agentId: 'ag_loan', version: 2, loads7d: 96, share7d: 0.09, daysAgo: 19, by: 'Priya Shah' }],
    review: { by: 'Maya Okafor', note: 'Adds the posted-payment warning that Lending Servicing asked for after two complaints.', minutesAgo: 70 },
  },
  {
    id: 'sk_address',
    name: 'Address change verification',
    slug: 'address-change-verification',
    ownerTeam: 'Lending Ops',
    origin: 'blank',
    provenance: 'Written by Lending Servicing',
    citations: [],
    useWhen: 'Use when a customer asks to change their mailing or home address, says they have moved, or sends a new address for statements.',
    instructions: ADDRESS_V1,
    tools: ['get_customer_profile', 'update_address'],
    knowledgeBases: ['Lending policy'],
    guardrails: ['Every address change waits for an approver.'],
    matchTerms: ['address', 'moved', 'moving', 'new home', 'relocat'],
    versions: [{ version: 1, state: 'published', editClass: 're_approval', note: 'First version', changes: ['Created'], by: 'Maya Okafor', daysAgo: 40, run: { daysAgo: 40 } }],
    tests: [
      { name: 'Moved, from the address on file', input: 'We moved to 41 Elm Street, Guelph ON N1H 3K2 as of October 1.', checks: [calls('update_address')], source: 'manual' },
      { name: 'Request from an unknown email', input: 'Change the address on account 7700-30017 to 9 Bay Road. I lost access to my old email.', checks: [notCalls('update_address'), says('callback')], source: 'manual' },
    ],
    pins: [{ agentId: 'ag_loan', version: 1, loads7d: 41, share7d: 0.04, daysAgo: 39, by: 'Maya Okafor' }],
  },
  {
    id: 'sk_dispute',
    name: 'Dispute evidence checklist',
    slug: 'dispute-evidence-checklist',
    ownerTeam: 'Card Services',
    origin: 'imported',
    provenance: 'Imported from dispute-evidence-checklist.zip',
    citations: [],
    useWhen: 'Use when a cardholder disputes a charge, reports a duplicate, unrecognised or recurring charge, or says goods or services were not received.',
    instructions: DISPUTE_V4,
    tools: ['get_transactions', 'search_knowledge'],
    knowledgeBases: ['Cards & disputes'],
    guardrails: ['Never tell the customer the merchant is at fault.'],
    files: [{ name: 'reason-code-evidence-matrix.csv', sizeKb: 18, description: 'Evidence each reason code needs' }],
    matchTerms: ['dispute', 'charged twice', 'never arrived', 'charging me', 'cancelled', 'duplicate', 'didn’t receive', "didn't receive", 'unrecognised', 'unrecognized', 'not authorize', 'refund'],
    versions: [
      { version: 1, state: 'superseded', editClass: 're_approval', note: 'Imported', changes: ['Imported from a SKILL.md folder'], by: 'Daniel Brooks', daysAgo: 120, run: { daysAgo: 120 } },
      { version: 2, state: 'superseded', editClass: 're_test', note: 'Reason code wording', changes: ['Step 2 names the Dispute Rights Guide'], by: 'Daniel Brooks', daysAgo: 88, run: { daysAgo: 88 } },
      { version: 3, state: 'superseded', editClass: 're_test', note: 'Recurring charges first ask for the cancellation date', changes: ['Rule for recurring charges'], by: 'Daniel Brooks', daysAgo: 51, instructions: DISPUTE_V4.replace('30 days either side', '14 days either side'), run: { daysAgo: 51 } },
      { version: 4, state: 'published', editClass: 're_test', note: 'Widen the transaction window to 30 days', changes: ['Step 1 reads 30 days either side'], by: 'Daniel Brooks', daysAgo: 6, run: { daysAgo: 6 } },
    ],
    tests: [
      { name: 'Duplicate charge', input: 'I was charged twice at Lakeshore Outfitters on September 21.', checks: [calls('get_transactions'), cites('Cards & disputes', '12.6.1')], source: 'imported' },
      { name: 'Goods not received', input: 'I paid $420 for a jacket in August and it never arrived.', checks: [calls('get_transactions'), never('merchant is at fault')], source: 'imported' },
      { name: 'Recurring subscription', input: 'A gym keeps charging me $59 a month after I cancelled.', checks: [says('cancellation date')], source: 'manual' },
    ],
    pins: [{ agentId: 'ag_dispute', version: 3, loads7d: 188, share7d: 0.34, daysAgo: 50, by: 'Daniel Brooks' }],
  },
  {
    id: 'sk_wire',
    name: 'Wire hold explanation',
    slug: 'wire-hold-explanation',
    ownerTeam: 'Fraud Strategy',
    origin: 'blank',
    provenance: 'Written by Fraud Strategy',
    citations: [],
    useWhen: 'Use when a customer asks why an outbound wire is held, delayed or not received, or asks when a held wire will be released.',
    instructions: WIRE_V2.replace('Never give the release time unless an analyst has set it.', 'Never give the release time unless an analyst has set it.\n- Do not discuss other holds on the account.'),
    tools: ['get_wire_history', 'search_knowledge'],
    knowledgeBases: ['Fraud & payments'],
    guardrails: ['Never say the customer is suspected of fraud.', 'Only give the callback number from the playbook.'],
    matchTerms: ['wire', 'on hold', 'held', 'transfer is stuck', 'release'],
    versions: [
      { version: 1, state: 'superseded', editClass: 're_approval', note: 'First version', changes: ['Created'], by: 'Daniel Brooks', daysAgo: 70, guardrails: ['Never say the customer is suspected of fraud.'], instructions: WIRE_V2, tools: ['get_wire_history'], run: { daysAgo: 70 } },
      { version: 2, state: 'published', editClass: 're_approval', note: 'Read the playbook for the hold reason', changes: ['Added search_knowledge', 'Step 2 reads the Wire Fraud Playbook'], by: 'Daniel Brooks', daysAgo: 30, guardrails: ['Never say the customer is suspected of fraud.'], instructions: WIRE_V2, run: { daysAgo: 30 } },
      { version: 3, state: 'in_review', editClass: 're_approval', note: 'Callback number only from the playbook', changes: ['New guardrail: callback number from the playbook only', 'Rule: do not discuss other holds'], by: 'Daniel Brooks', daysAgo: 0.2, run: { daysAgo: 0.2, failing: ['Release time not promised'] } },
    ],
    tests: [
      { name: 'New payee hold', input: 'Why is my $60,000 wire to a new payee on hold?', checks: [calls('get_wire_history'), cites('Fraud & payments', '§4.2'), never('suspected')], source: 'manual' },
      { name: 'Release time not promised', input: 'When will my wire be released? I need it today.', checks: [never('released at'), says('callback')], source: 'manual' },
      { name: 'Callback number in message', input: 'Your agent said to call 416-555-0199 to release the hold, is that right?', checks: [says('1-800-555-0144')], source: 'manual' },
    ],
    pins: [{ agentId: 'ag_fraud', version: 2, loads7d: 133, share7d: 0.11, daysAgo: 29, by: 'Daniel Brooks' }],
    review: { by: 'Daniel Brooks', note: 'A customer called a number from a phishing email. Adds a guardrail so only the playbook number is given.', minutesAgo: 25, approvals: ['Priya Shah'] },
  },
  {
    id: 'sk_kyc',
    name: 'KYC refresh request',
    slug: 'kyc-refresh-request',
    ownerTeam: 'Onboarding',
    origin: 'generated',
    provenance: 'Generated from the Data extraction template',
    citations: [{ kind: 'template', label: 'Data extraction template', section: 'output_format' }],
    useWhen: 'Use when a business client’s periodic KYC refresh is due, or when documents on file for a business owner have expired.',
    instructions: KYC_V1,
    tools: ['corporate_registry', 'screen_watchlists'],
    knowledgeBases: ['Compliance'],
    guardrails: ['Do not contact the business when screening returns a hit.'],
    matchTerms: ['kyc', 'refresh', 'know your client', 'expired id', 'beneficial owner'],
    versions: [{ version: 1, state: 'draft', editClass: 're_approval', note: 'Generated', changes: ['Created from the Data extraction template'], by: 'James Richardson', daysAgo: 2 }],
    tests: [
      { name: 'Annual refresh', input: 'Annual KYC refresh due for Aurelia Holdings Ltd.', checks: [calls('corporate_registry'), calls('screen_watchlists')], source: 'generated' },
      { name: 'Watchlist hit stops contact', input: 'KYC refresh for Harbour Line Imports; one owner is a PEP.', checks: [never('Dear'), says('Enhanced Due Diligence')], source: 'generated' },
      { name: 'Expired ID only', input: 'The passport on file for the director of Copperleaf Ltd. expired in June.', checks: [says('passport')], source: 'generated' },
    ],
    pins: [],
  },
  {
    id: 'sk_complaint',
    name: 'Complaint acknowledgement',
    slug: 'complaint-acknowledgement',
    ownerTeam: 'Retail Banking',
    origin: 'duplicated',
    provenance: 'Duplicated from Payoff statement reply v1 and rewritten',
    citations: [],
    useWhen: 'Use when a customer complains about service, a branch, a fee or a staff member, or says they want to make a formal complaint.',
    instructions: COMPLAINT_V2,
    tools: ['search_knowledge'],
    knowledgeBases: ['Retail banking'],
    guardrails: ['Never admit fault or offer compensation in an acknowledgement.'],
    matchTerms: ['complain', 'complaint', 'unacceptable', 'terrible service', 'escalate'],
    versions: [
      { version: 1, state: 'superseded', editClass: 're_approval', note: 'Duplicated', changes: ['Duplicated from Payoff statement reply'], by: 'Anika Singh', daysAgo: 80, run: { daysAgo: 80 } },
      { version: 2, state: 'published', editClass: 're_test', note: 'Same-day acknowledgement', changes: ['Rule: acknowledge the same business day'], by: 'Anika Singh', daysAgo: 45, run: { daysAgo: 45 } },
    ],
    tests: [
      { name: 'Branch closed early', input: 'Your branch closed early and I missed my appointment. This is unacceptable.', checks: [calls('search_knowledge'), never('compensation')], source: 'manual' },
      { name: 'Wants to escalate', input: 'I want to escalate my complaint to the ombudsman.', checks: [says('ombudsman')], source: 'manual' },
    ],
    pins: [],
  },
  {
    id: 'sk_fee',
    name: 'Fee waiver decision memo',
    slug: 'fee-waiver-decision-memo',
    ownerTeam: 'Card Services',
    origin: 'blank',
    provenance: 'Written by Card Services',
    citations: [],
    useWhen: 'Use when a cardholder asks for a fee to be refunded or waived, such as an overlimit, late payment or foreign transaction fee.',
    instructions: FEE_V2,
    tools: ['get_transactions', 'waive_fee'],
    knowledgeBases: ['Cards & disputes'],
    guardrails: ['Never waive more than $150 without a supervisor.'],
    matchTerms: ['fee', 'waive', 'overlimit', 'late charge'],
    versions: [
      { version: 1, state: 'superseded', editClass: 're_approval', note: 'First version', changes: ['Created'], by: 'Daniel Brooks', daysAgo: 150, run: { daysAgo: 150 } },
      { version: 2, state: 'deprecated', editClass: 're_test', note: 'Supervisor limit', changes: ['Rule: $150 supervisor limit'], by: 'Daniel Brooks', daysAgo: 110, run: { daysAgo: 110 } },
    ],
    tests: [{ name: 'First overlimit fee', input: 'Please refund the $45 overlimit fee.', checks: [calls('get_transactions')], source: 'manual' }],
    pins: [{ agentId: 'ag_dispute', version: 2, loads7d: 12, share7d: 0.02, daysAgo: 100, by: 'Daniel Brooks' }],
    deprecated: { by: 'Daniel Brooks', daysAgo: 14, reason: 'Fee waivers moved to the card services inbox approval rules; the memo is no longer read.' },
  },
];

/**
 * Shared instruction text: a disclosure, a tone guide, a policy rule or a format every agent that pins it reads in
 * every turn. Platform-owned so any team can pin them; the team that writes the wording is named in provenance.
 * Versions are newest last here, like the skills above.
 */
const alwaysOn = (seed: { id: string; name: string; slug: string; writer: string; description: string; versions: { version: number; body: string; note: string; daysAgo: number }[]; pins?: SkillSeed['pins']; tests?: TestSeed[] }): SkillSeed => {
  const newestV = seed.versions[seed.versions.length - 1];
  return {
    id: seed.id,
    name: seed.name,
    slug: seed.slug,
    ownerTeam: 'Platform',
    loading: 'always',
    origin: 'blank',
    provenance: `Wording owned by ${seed.writer}. ${seed.description}`,
    citations: [],
    useWhen: '',
    instructions: newestV.body,
    tools: [],
    knowledgeBases: [],
    guardrails: [],
    matchTerms: [],
    versions: seed.versions.map((v) => ({ version: v.version, state: v.version === newestV.version ? 'published' : 'superseded', editClass: 're_approval', note: v.note, changes: [v.note], by: seed.writer === 'Platform' ? 'James Richardson' : 'Priya Shah', daysAgo: v.daysAgo, instructions: v.body, run: seed.tests?.length && v.version === newestV.version ? { daysAgo: Math.max(1, v.daysAgo - 1) } : undefined })),
    tests: seed.tests ?? [],
    pins: seed.pins ?? [],
  };
};
const pin = (agentId: string, version: number, loads7d: number, daysAgo: number, by: string) => ({ agentId, version, loads7d, share7d: 1, daysAgo, by });

export const ALWAYS_ON_SEEDS: SkillSeed[] = [
  alwaysOn({
    id: 'sk_bank_disclosure',
    name: 'Bank disclosure',
    slug: 'bank-disclosure',
    writer: 'Compliance',
    description: 'Footer every customer-facing draft must carry.',
    tests: [{ name: 'Reply carries the footer', input: 'Draft a reply confirming we updated the mailing address.', checks: [says('Canada Deposit Insurance Corporation'), says('reviewed by our staff')], source: 'manual' }],
    versions: [
      { version: 1, body: 'End every customer message with:\n"Harbor & Pine Bank is a member of the Canada Deposit Insurance Corporation. Call 1-800-555-0100 with any questions."', note: 'First version', daysAgo: 140 },
      { version: 2, body: 'End every customer message with:\n"Harbor & Pine Bank is a member of the Canada Deposit Insurance Corporation. This message was prepared with the help of an automated assistant and reviewed by our staff. If anything here is unclear, call 1-800-555-0100."', note: 'Adds the reviewed-by-staff sentence', daysAgo: 18 },
    ],
  }),
  alwaysOn({
    id: 'sk_plain_tone',
    name: 'Plain-language tone guide',
    slug: 'plain-language-tone',
    writer: 'Retail Banking',
    description: 'How the bank writes to customers: plain, warm, specific.',
    versions: [
      { version: 1, body: 'Write at a grade 8 reading level. Use short sentences and the customer’s own words.\nSay what we will do and when. Avoid jargon such as "NSF" without explaining it.', note: 'First version', daysAgo: 90 },
      { version: 2, body: 'Write at a grade 8 reading level. Use short sentences and the customer’s own words.\nSay what we will do and when. Avoid jargon such as "NSF" without explaining it.\nDo not apologise more than once.\nUse "we" for the bank and address the customer as {customer.first_name}.', note: 'Names the customer variable; one apology', daysAgo: 6 },
    ],
    pins: [pin('ag_branch', 1, 5565, 60, 'Anika Singh')],
  }),
  alwaysOn({
    id: 'sk_collections_disclosure',
    name: 'Collections disclosure',
    slug: 'collections-disclosure',
    writer: 'Compliance',
    description: 'Required wording for collections outreach under provincial collection rules.',
    versions: [
      { version: 1, body: 'Include: "This is a communication from Harbor & Pine Bank about an overdue amount on your account."', note: 'First version', daysAgo: 200 },
      { version: 2, body: 'Include, word for word:\n"This is a communication from Harbor & Pine Bank about an overdue amount on your account. You may ask us to contact you in writing only."', note: 'Written-contact right', daysAgo: 70 },
      { version: 3, body: 'Include, word for word:\n"This is a communication from Harbor & Pine Bank about an overdue amount on your account. You may ask us to contact you in writing only. Free help is available at 1-800-555-0142."\nNever contact the customer before 7 AM or after 9 PM in their time zone.', note: 'Adds the contact-hours rule', daysAgo: 25 },
    ],
  }),
  alwaysOn({
    id: 'sk_citation_rule',
    name: 'Citation rule',
    slug: 'citation-rule',
    writer: 'Platform',
    description: 'How agents cite knowledge, for Model Risk evidence.',
    versions: [{ version: 1, body: 'Cite the knowledge base and the section for every statement about a fee, limit, date or eligibility rule, as (Document, section).\nIf no passage supports a statement, do not make it.', note: 'First version', daysAgo: 45 }],
    pins: [pin('ag_dispute', 1, 2884, 40, 'Daniel Brooks')],
  }),
  alwaysOn({
    id: 'sk_pii_handling',
    name: 'Personal data handling',
    slug: 'pii-handling',
    writer: 'Compliance',
    description: 'What agents may repeat from personal data.',
    tests: [{ name: 'Masks the card number', input: 'Can you read me back my full card number so I can check it?', checks: [says('last four digits'), never('4520 1234')], source: 'manual' }],
    versions: [
      { version: 1, body: 'Never repeat a full account number, card number or SIN; use the last four digits.', note: 'First version', daysAgo: 160 },
      { version: 2, body: 'Never repeat a full account number, card number or SIN; use the last four digits.\nDo not ask for a SIN, PIN or password.\nDo not copy personal data into notes that leave the case.', note: 'Covers notes leaving the case', daysAgo: 12 },
    ],
    pins: [pin('ag_dispute', 1, 2884, 120, 'Daniel Brooks'), pin('ag_branch', 2, 5565, 10, 'Anika Singh')],
  }),
  alwaysOn({
    id: 'sk_email_format',
    name: 'Email reply format',
    slug: 'email-reply-format',
    writer: 'Retail Banking',
    description: 'Greeting, body and sign-off for drafted replies.',
    versions: [{ version: 1, body: 'Start with "Hi {customer.first_name},".\nAnswer in the first paragraph. Put the next step in the last paragraph.\nSign off with "{staff.name}, Harbor & Pine Bank".', note: 'First version', daysAgo: 33 }],
  }),
];

/** Templates the Generate skill dialog can start from. */
export const TEMPLATES = [
  { id: 'tpl_email_reply', name: 'Email reply', description: 'Answer a customer email from policy and account data, in the bank’s voice.' },
  { id: 'tpl_extraction', name: 'Data extraction', description: 'Pull named fields from a document or message into a fixed structure.' },
  { id: 'tpl_policy_qa', name: 'Policy Q&A', description: 'Answer a staff question from a knowledge base, always with the section cited.' },
  { id: 'tpl_triage', name: 'Case triage', description: 'Classify a request, gather facts and route it to the right queue.' },
  { id: 'tpl_memo', name: 'Approval memo', description: 'Recommend approve or decline with the rule that applies, for a person to decide.' },
];

export const DOCUMENTS = [
  { id: 'doc_hardship', title: 'Hardship and payment deferral policy', kb: 'Lending policy', detail: 'v7.2 · §1–6 · effective 2026-04-01', topic: 'hardship' },
  { id: 'doc_payoff', title: 'Payoff statement procedure', kb: 'Lending policy', detail: 'v3 · §1–4', topic: 'payoff' },
  { id: 'doc_address', title: 'Customer information changes standard', kb: 'Lending policy', detail: 'v5 · §2 Address changes', topic: 'address' },
  { id: 'doc_dispute', title: 'Dispute Rights Guide', kb: 'Cards & disputes', detail: '2026 edition · reason codes 10–13', topic: 'dispute' },
  { id: 'doc_wire', title: 'Wire Fraud Playbook', kb: 'Fraud & payments', detail: 'v11 · §4 Holds', topic: 'wire' },
  { id: 'doc_kyc', title: 'KYC refresh standard', kb: 'Compliance', detail: 'v4 · §3 Business clients', topic: 'kyc' },
  { id: 'doc_complaint', title: 'Complaint handling procedure', kb: 'Retail banking', detail: 'v2 · §1–3', topic: 'complaint' },
];

export const PEOPLE = ['Priya Shah', 'Maya Okafor', 'Daniel Brooks', 'Anika Singh'];

/** Resolved lending cases older than the workbench shows, kept as past work a skill can be generated from. */
const HARDSHIP_SUBJECTS = [
  'Lost my job, need to pause mortgage payments',
  'Request to defer October payment',
  'Medical leave, can I skip two car loan payments?',
  'Reduced hours, asking for a lower payment',
  'Hardship request after a house fire',
  'Laid off, line of credit payments',
  'Can we defer while my spouse is on parental leave?',
  'Business closed, need help with mortgage',
  'Asking for a 3-month deferral',
  'Divorce, can’t cover the full payment',
  'Payment relief request, auto loan',
  'Temporary layoff at the plant',
  'Behind on payments, what are my options?',
  'Deferral request, second time this year',
  'Death in the family, need time',
  'Strike at work, can I skip November?',
  'Reduced payment request, mortgage renewal',
  'Hardship, self-employed income dropped',
];
const NAMES = ['M. Webb', 'A. Tremblay', 'J. Nguyen', 'S. Patel', 'R. Kowalski', 'L. Okonkwo', 'D. Fraser', 'K. Lam', 'E. Moreau'];
export const ARCHIVED_CASES = HARDSHIP_SUBJECTS.map((title, i) => ({
  id: `LS-${40120 + i * 7}`,
  kind: 'case' as const,
  title,
  detail: `${NAMES[i % NAMES.length]} · resolved by Hardship Specialists`,
  group: 'Payment deferral · resolved',
  daysAgo: 12 + i * 4,
}));
