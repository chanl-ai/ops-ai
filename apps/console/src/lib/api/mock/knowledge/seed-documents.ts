import type { SampleDocument } from '@/lib/types/knowledge-ingest';

/**
 * Full bodies for the documents the demo questions are about. Everything else in the seed is a title with
 * generic policy text. Sections carry a `topic` so precedence can tell when two documents answer the same
 * point, and FAQ questions are written out so the `faq` strategy is deterministic.
 */
export interface SeedSection {
  heading: string;
  body: string;
  topic?: string;
  questions?: string[];
}

export interface SeedDocument {
  key: string;
  title: string;
  format: SampleDocument['format'];
  /** Precedence compares this (`policy`, `guide`, `faq`, …). */
  docClass: string;
  sections: SeedSection[];
  table?: { columns: string[]; rows: string[][] };
  /** Navigation and footer text a web page carries; `clean` removes it. */
  boilerplate?: string[];
  metadata?: Record<string, string>;
}

const disputeCredit: SeedDocument = {
  key: 'dispute_credit',
  title: 'Dispute rights guide — credit cards',
  format: 'policy',
  docClass: 'guide',
  metadata: { product: 'credit_card', jurisdiction: 'CA' },
  sections: [
    { heading: '1. Who this guide is for', body: 'Card Services agents and branch staff handling a cardholder’s dispute of a credit card transaction. It applies to Northfield Visa and Mastercard credit cards.' },
    {
      heading: '2. Time limits',
      topic: 'dispute_window',
      body: 'A cardholder can dispute a credit card transaction within 120 days of the statement date on which it first appeared. Disputes for goods not received run from the expected delivery date, up to 540 days from the transaction. Late disputes are declined unless the card network extends the window.',
      questions: ['How long does a customer have to dispute a credit card charge?', 'When does the dispute window start?'],
    },
    {
      heading: '3. Duplicate processing (reason code 12.6)',
      topic: 'duplicate_charge',
      body: 'Reason code 12.6 covers a transaction processed more than once. Collect both transaction references and confirm the amount and merchant match. Sub-code 12.6.1 is a duplicate on the same day; 12.6.2 is a charge paid by other means. Raise the chargeback within 120 days of the second posting.',
      questions: ['Which reason code covers a duplicate charge?', 'What evidence does a duplicate charge dispute need?'],
    },
    {
      heading: '4. Dispute declaration (form NF-2207)',
      topic: 'dispute_form',
      body: 'Fraud and goods-not-received disputes over $100 need a signed dispute declaration, form NF-2207. The cardholder can sign it in the app, at a branch or by e-signature. Do not raise the chargeback until the signed form is on the case.',
      questions: ['When is a signed dispute declaration needed?', 'How can a cardholder sign the dispute form?'],
    },
    {
      heading: '5. Provisional credit',
      topic: 'provisional_credit',
      body: 'Credit card disputes over $50 receive provisional credit within 10 business days of the dispute being filed. The credit is reversed if the merchant’s representment is accepted; give the cardholder 5 business days’ notice before reversing it.',
      questions: ['When does a disputed credit card charge get provisional credit?'],
    },
    { heading: '6. Related documents', body: 'Provisional credit policy. Chargeback reason codes — processing errors. Dispute letter templates.' },
  ],
};

const disputeDebit: SeedDocument = {
  key: 'dispute_debit',
  title: 'Dispute rights guide — debit cards',
  format: 'policy',
  docClass: 'guide',
  metadata: { product: 'debit_card', jurisdiction: 'CA' },
  sections: [
    {
      heading: '1. Time limits',
      topic: 'dispute_window',
      body: 'A cardholder can dispute an unauthorised debit card transaction within 60 days of the statement date. Liability is limited to $50 when a lost or stolen card is reported within 2 business days.',
      questions: ['How long does a customer have to dispute a debit card transaction?'],
    },
    {
      heading: '2. Provisional credit',
      topic: 'provisional_credit',
      body: 'Debit card disputes receive provisional credit within 10 business days, or 20 business days for accounts open less than 30 days.',
      questions: ['When does a debit card dispute get provisional credit?'],
    },
    { heading: '3. Interac e-Transfer', body: 'Interac e-Transfer disputes follow the Interac rules and are not chargebacks. Open a recall in the payments system instead.' },
  ],
};

const codesProcessing: SeedDocument = {
  key: 'codes_processing',
  title: 'Chargeback reason codes — processing errors',
  format: 'policy',
  docClass: 'reference',
  metadata: { product: 'cards', jurisdiction: 'CA' },
  sections: [
    { heading: '12.5 Incorrect amount', topic: 'incorrect_amount', body: 'Reason code 12.5: the cardholder was charged an amount different from the one agreed. Attach the receipt showing the agreed amount.' },
    { heading: '12.6 Duplicate processing or paid by other means', topic: 'duplicate_charge', body: 'Reason code 12.6: the same transaction posted more than once (12.6.1), or the cardholder paid by other means (12.6.2). Both references are required.' },
    { heading: '12.7 Invalid data', body: 'Reason code 12.7: the authorisation was obtained with invalid data, such as a wrong expiry date or merchant category.' },
  ],
};

const codesFraud: SeedDocument = {
  key: 'codes_fraud',
  title: 'Chargeback reason codes — fraud',
  format: 'policy',
  docClass: 'reference',
  metadata: { product: 'cards', jurisdiction: 'CA' },
  sections: [
    { heading: '10.4 Other fraud — card-absent environment', topic: 'fraud_codes', body: 'Reason code 10.4: the cardholder did not authorise a card-not-present transaction. The cardholder signs form NF-2207 and the card is reissued.' },
    { heading: '10.3 Other fraud — card-present environment', topic: 'fraud_codes', body: 'Reason code 10.3: a counterfeit or stolen card was used in person at a terminal without chip verification.' },
    { heading: '10.5 Fraud monitoring program', body: 'Reason code 10.5: the merchant was identified by the network’s fraud monitoring program. No cardholder declaration is needed.' },
  ],
};

const provisionalCredit: SeedDocument = {
  key: 'provisional_credit_policy',
  title: 'Provisional credit policy',
  format: 'policy',
  docClass: 'policy',
  metadata: { product: 'cards', jurisdiction: 'CA' },
  sections: [
    {
      heading: '2. When provisional credit applies',
      topic: 'provisional_credit',
      body: 'Provisional credit is granted within 10 business days for credit card disputes over $50 and for every debit card dispute. Card Services leads approve provisional credits above $500; branch staff cannot grant them.',
      questions: ['When does provisional credit apply to a disputed card payment?', 'Who approves a provisional credit above $500?'],
    },
    { heading: '3. Reversal', topic: 'provisional_reversal', body: 'A provisional credit is reversed only after the merchant’s representment is accepted and the cardholder has had 5 business days’ notice.' },
  ],
};

const wireHold: SeedDocument = {
  key: 'wire_hold',
  title: 'Wire Fraud Playbook §4.2 New-payee wires',
  format: 'policy',
  docClass: 'playbook',
  metadata: { product: 'wire', jurisdiction: 'CA' },
  sections: [
    {
      heading: '4.2.1 When the hold applies',
      topic: 'new_payee_hold',
      body: 'Hold any outgoing wire above $10,000 to a payee added in the last 24 hours. The hold also applies when the payee’s account details changed in the last 24 hours.',
      questions: ['How long do we hold a wire to a new payee?', 'Which wires get the new-payee hold?'],
    },
    {
      heading: '4.2.2 Call-back',
      topic: 'call_back',
      body: 'Call the customer back on the phone number on file, never a number given in the wire instructions. Confirm the payee, amount and purpose, and record the call on the case.',
      questions: ['Which phone number do we use for a wire call-back?'],
    },
    {
      heading: '4.2.3 Release',
      topic: 'wire_release_authority',
      body: 'An analyst may release the hold after a successful call-back when the wire risk score is below 70. At a score of 70 or above the duty lead approves the release.',
      questions: ['Who can release a held wire?', 'Who approves a hold release at score 70 or above?'],
    },
    {
      heading: '4.2.4 No answer',
      topic: 'no_answer',
      body: 'If the customer cannot be reached within 4 business hours, return the wire and close the case as unverified. Tell the customer by secure message.',
      questions: ['What happens when the customer does not answer the call-back?'],
    },
    { heading: '4.2.5 Hold codes', topic: 'hold_codes', body: 'Use hold code WH-24 for a new-payee hold and WH-CB while a call-back is pending.' },
  ],
};

const wireRelease: SeedDocument = {
  key: 'wire_release',
  title: 'Wire release and escalation authority',
  format: 'policy',
  docClass: 'playbook',
  metadata: { product: 'wire', jurisdiction: 'CA' },
  sections: [
    {
      heading: 'Release authority',
      topic: 'wire_release_authority',
      body: 'Analyst: release below risk score 70 and under $250,000. Duty lead: risk score 70 or above, or $250,000 and over. Head of fraud operations: any wire to a high-risk jurisdiction.',
    },
  ],
};

const wireThresholds: SeedDocument = {
  key: 'wire_thresholds',
  title: 'Wire risk score thresholds',
  format: 'policy',
  docClass: 'model_doc',
  metadata: { product: 'wire', jurisdiction: 'CA' },
  sections: [
    { heading: 'Bands', topic: 'wire_release_authority', body: 'Scores of 70 and above are high risk and route to the duty lead; 40 to 69 route to an analyst; below 40 release automatically once any new-payee hold clears.' },
    { heading: 'Recalibration', body: 'Thresholds are recalibrated quarterly against confirmed fraud outcomes and approved by Model Risk.' },
  ],
};

const travelRule: SeedDocument = {
  key: 'travel_rule',
  title: 'Travel rule for wire transfers',
  format: 'policy',
  docClass: 'procedure',
  metadata: { product: 'wire', jurisdiction: 'CA' },
  sections: [
    { heading: '1. Required information', topic: 'travel_rule', body: 'Originator and beneficiary name, address and account number accompany every wire of $1,000 or more.' },
    { heading: '2. Missing information', topic: 'travel_rule_missing', body: 'An incoming wire missing originator details is held for 2 business days while the sending bank is asked for them. If they do not arrive, return the wire.' },
  ],
};

const feeSchedule: SeedDocument = {
  key: 'fee_schedule',
  title: 'Fee schedule 2026 Q3',
  format: 'table',
  docClass: 'schedule',
  metadata: { product: 'lending', jurisdiction: 'CA' },
  sections: [{ heading: 'Business and personal lending', body: 'Origination fees by product and loan amount. Fees are deducted at funding.' }],
  table: {
    columns: ['Product', 'Band', 'Origination fee', 'Minimum', 'Maximum', 'Secured', 'Effective', 'Notes'],
    rows: [
      ['Small business term loan', '<= $250,000', '1.00%', '$500', '$2,500', 'No', '2026-07-01', 'Waived for agricultural loans'],
      ['Small business term loan', '> $250,000', '0.75%', '$1,500', '$7,500', 'No', '2026-07-01', ''],
      ['Small business term loan', '> $250,000', '0.50%', '$1,000', '$5,000', 'Commercial property', '2026-07-01', 'Requires a first charge'],
      ['Equipment financing', '<= $100,000', '1.25%', '$300', '$1,250', 'Equipment', '2026-07-01', ''],
      ['Personal loan', 'any', '0.00%', '$0', '$0', 'No', '2026-07-01', 'No origination fee'],
      ['Line of credit', '<= $50,000', '$150 flat', '$150', '$150', 'No', '2026-07-01', ''],
      ['Line of credit', '> $50,000', '0.25%', '$150', '$1,000', 'No', '2026-07-01', ''],
    ],
  },
};

const lendingSmallBusiness: SeedDocument = {
  key: 'lending_sb',
  title: 'Lending policy v6 — small business',
  format: 'policy',
  docClass: 'policy',
  metadata: { product: 'small_business_loan', jurisdiction: 'CA' },
  sections: [
    { heading: '7.1 Eligibility', topic: 'sb_eligibility', body: 'Businesses trading for at least 2 years with audited or reviewed statements. Start-ups go through the new-venture program instead.' },
    { heading: '7.2 Fees at funding', topic: 'origination_fee_timing', body: 'Origination fees are deducted from the advance at funding and are not refundable if the facility is repaid early. Amounts are set in the current fee schedule.' },
  ],
};

const deferralSections = (v: 1 | 2): SeedSection[] => [
  { heading: '1. Purpose', body: 'Sets when a borrower in temporary financial difficulty may defer loan payments, sometimes called a payment holiday or skip-a-payment.' },
  {
    heading: '2. Eligibility',
    topic: 'deferral_eligibility',
    body: v === 1 ? 'Personal loans and lines of credit in good standing for 6 months. One deferral request in any 12 months.' : 'Personal loans and lines of credit in good standing for 12 months. One deferral request in any 12 months.',
  },
  {
    heading: '3. How many payments',
    topic: 'deferral_limit',
    body:
      v === 1
        ? 'A borrower may defer up to 3 consecutive monthly payments. Interest continues to accrue and is added to the balance.'
        : 'A borrower may defer up to 2 consecutive monthly payments and must then make 6 regular payments before another deferral. Interest continues to accrue and is added to the balance.',
    questions: ['How many payments can a borrower defer?', 'Can a customer skip a loan payment?'],
  },
  {
    heading: '4. Approval',
    topic: 'deferral_approval',
    body: v === 1 ? 'Branch managers approve deferrals of up to 3 payments.' : 'Branch managers approve a one-payment deferral; two payments need Lending Ops approval.',
  },
  ...(v === 2 ? [{ heading: '5. Mortgages', body: 'Mortgage deferrals follow the hardship program guidelines, not this policy.' }] : []),
];

const deferralV1: SeedDocument = { key: 'deferral_v1', title: 'Payment deferral policy', format: 'policy', docClass: 'policy', metadata: { product: 'personal_loan', jurisdiction: 'CA' }, sections: deferralSections(1) };
const deferralV2: SeedDocument = { key: 'deferral_v2', title: 'Payment deferral policy', format: 'policy', docClass: 'policy', metadata: { product: 'personal_loan', jurisdiction: 'CA' }, sections: deferralSections(2) };

const annualFee: SeedDocument = {
  key: 'annual_fee',
  title: 'Annual fee',
  format: 'article',
  docClass: 'pricing',
  metadata: { product: 'credit_card', jurisdiction: 'CA' },
  boilerplate: ['<nav>Personal › Credit cards › Pricing › Annual fee</nav>', 'Was this page helpful? Yes · No', '© 2026 Northfield Bank. All rights reserved. Privacy · Accessibility · Security'],
  sections: [
    { heading: 'Annual fees by card', topic: 'annual_fee_amount', body: 'Northfield Rewards Visa: $120 a year. Low Rate Mastercard: $29 a year. Student Visa: no annual fee.' },
    { heading: 'Cancellation and refunds', topic: 'annual_fee_refund', body: 'The annual fee is refunded in full when the card is closed within 30 days of the fee posting. After 30 days the fee is not refunded.' },
    { heading: 'Switching cards', topic: 'annual_fee_switch', body: 'Moving to a no-fee card takes effect from the next statement, and the current year’s fee is pro-rated.' },
  ],
};

const branchFaq: SeedDocument = {
  key: 'branch_faq',
  title: 'Branch FAQ',
  format: 'faq',
  docClass: 'faq',
  metadata: { product: 'retail', jurisdiction: 'CA' },
  sections: [
    { heading: 'Q: Can a customer get an annual card fee refunded?', topic: 'annual_fee_refund', body: 'Within 30 days it is a full refund. After the first 30 days we do not refund the fee; we can move the customer to a no-fee card from the next statement.' },
    { heading: 'Q: What is the NSF fee?', topic: 'nsf_fee', body: 'A non-sufficient funds fee of $45 applies per returned item. Waive it once in 12 months for customers with direct deposit.' },
    { heading: 'Q: When is the wire cut-off?', topic: 'wire_cutoff', body: 'Wires booked at Toronto branches before 2:30 pm ET go the same day. Other branches book wires through the contact centre, with a 1:00 pm local cut-off.' },
    { heading: 'Q: Can a branch certify a cheque for a non-customer?', topic: 'certified_cheque', body: 'No. Certified cheques are for account holders only. A bank draft can be sold to a non-customer for $10.' },
    { heading: 'Q: How does a customer defer a loan payment?', topic: 'deferral_how', body: 'They request a payment deferral in the app or at a branch; the branch manager checks eligibility against the payment deferral policy.' },
  ],
};

const retention: SeedDocument = {
  key: 'retention',
  title: 'Record keeping and retention',
  format: 'policy',
  docClass: 'procedure',
  metadata: { jurisdiction: 'CA' },
  sections: [
    { heading: '3. Retention periods', topic: 'retention_period', body: 'Customer due diligence records are kept for 7 years after the relationship ends. Records must be producible within 30 days of a request.', questions: ['How long do we keep customer due diligence records?'] },
    { heading: '4. Format', topic: 'retention_format', body: 'Records may be held in the case system rather than on paper, as long as they can be produced on request.' },
  ],
};

const retention2025: SeedDocument = {
  key: 'retention_2025',
  title: 'Record keeping and retention (2025)',
  format: 'policy',
  docClass: 'procedure',
  metadata: { jurisdiction: 'CA' },
  sections: [{ heading: '3. Retention periods', topic: 'retention_period', body: 'Customer due diligence records are kept for 5 years after the relationship ends.' }],
};

const retentionOntario: SeedDocument = {
  key: 'retention_on',
  title: 'Record keeping and retention — Ontario addendum',
  format: 'policy',
  docClass: 'addendum',
  metadata: { jurisdiction: 'ON' },
  sections: [{ heading: '2. Start of the retention period', topic: 'retention_start', body: 'In Ontario the retention period starts at account closure, not at the last transaction. Records tied to a suspicious transaction report follow the same period.' }],
};

const retentionFaq: SeedDocument = {
  key: 'retention_faq',
  title: 'Record keeping and retention — FAQ',
  format: 'faq',
  docClass: 'faq',
  metadata: { jurisdiction: 'CA' },
  sections: [{ heading: 'Q: How do we store records?', topic: 'retention_format', body: 'Store records in the case system; paper copies are scanned and shredded after 30 days.' }],
};

const helpArticle: SeedDocument = {
  key: 'help_dispute',
  title: 'How do I dispute a card transaction?',
  format: 'article',
  docClass: 'help',
  metadata: { product: 'cards' },
  boilerplate: ['<nav>Help centre › Cards › Disputes</nav>', '<div class="cookie-banner">We use cookies to improve your experience. Accept · Manage</div>', 'Was this article helpful? 👍 👎', '© 2026 Northfield Bank · Contact us · Branch locator'],
  sections: [
    { heading: 'Before you dispute', body: 'Contact the merchant first. Many charges are resolved by a refund within a few days.' },
    { heading: 'Dispute in the app', topic: 'dispute_how', body: 'Open the transaction, tap Report a problem and choose the reason. Most disputes get a provisional credit within 10 business days.' },
    { heading: 'What happens next', topic: 'dispute_timeline', body: 'We contact the merchant’s bank. Most disputes are resolved within 45 days, and we message you at each step.' },
  ],
};

const emailTemplate: SeedDocument = {
  key: 'email_provisional',
  title: 'Provisional credit letter',
  format: 'email',
  docClass: 'template',
  metadata: { product: 'cards' },
  sections: [
    { heading: 'Subject', body: 'We have credited your account while we look into your dispute' },
    { heading: 'Body', topic: 'provisional_letter', body: 'Dear {customer.first_name}, we have added a provisional credit of {dispute.amount} to your account while we investigate. If the merchant shows the charge was valid, we will reverse the credit after giving you 5 business days’ notice.' },
    { heading: 'Sign-off', body: 'Card Services, Northfield Bank' },
  ],
};

export const SEED_DOCUMENTS: SeedDocument[] = [
  disputeCredit,
  disputeDebit,
  codesProcessing,
  codesFraud,
  provisionalCredit,
  wireHold,
  wireRelease,
  wireThresholds,
  travelRule,
  feeSchedule,
  lendingSmallBusiness,
  deferralV1,
  deferralV2,
  annualFee,
  branchFaq,
  retention,
  retention2025,
  retentionOntario,
  retentionFaq,
  helpArticle,
  emailTemplate,
];

export const docByKey = (key: string) => SEED_DOCUMENTS.find((d) => d.key === key);

/** Which seeded item carries which full body. Two items with the same body share a digest, so they are indexed once. */
export const FEATURED: Record<string, string> = {
  src_contracts_it_0: 'dispute_debit',
  src_contracts_it_1: 'dispute_credit',
  src_contracts_it_3: 'codes_fraud',
  src_contracts_it_4: 'codes_processing',
  src_contracts_it_5: 'provisional_credit_policy',
  src_eng_confluence_it_0: 'wire_hold',
  src_eng_confluence_it_1: 'wire_release',
  src_eng_confluence_it_380: 'travel_rule',
  src_github_docs_it_3: 'wire_thresholds',
  src_hr_sharepoint_it_10: 'travel_rule',
  src_hr_sharepoint_it_12: 'retention',
  src_hr_sharepoint_it_42: 'retention_on',
  src_hr_sharepoint_it_162: 'retention_faq',
  src_hr_sharepoint_it_402: 'retention_2025',
  src_lending_policies_it_1: 'lending_sb',
  src_lending_policies_it_2: 'fee_schedule',
  src_lending_policies_it_9: 'deferral_v1',
  src_lending_policies_it_10: 'deferral_v2',
  src_pricing_crawl_it_23: 'annual_fee',
  src_pricing_crawl_it_95: 'annual_fee',
  src_branch_faq_it_0: 'branch_faq',
};

/** Documents offered in the split preview, with the source they read as. */
export const SAMPLES: { key: string; sourceId?: string; sourceName: string; version?: string; effectiveDate?: string }[] = [
  { key: 'dispute_credit', sourceId: 'src_contracts', sourceName: 'Dispute rights guides' },
  { key: 'wire_hold', sourceId: 'src_eng_confluence', sourceName: 'Wire fraud playbook' },
  { key: 'fee_schedule', sourceId: 'src_lending_policies', sourceName: 'Lending policies and fee schedules' },
  { key: 'deferral_v2', sourceId: 'src_lending_policies', sourceName: 'Lending policies and fee schedules', version: 'v2.0', effectiveDate: '2026-03-01' },
  { key: 'retention', sourceId: 'src_hr_sharepoint', sourceName: 'AML & KYC procedures' },
  { key: 'annual_fee', sourceId: 'src_pricing_crawl', sourceName: 'Pricing site' },
  { key: 'branch_faq', sourceId: 'src_branch_faq', sourceName: 'Branch FAQ' },
  { key: 'help_dispute', sourceId: 'src_zendesk_draft', sourceName: 'Help centre articles' },
  { key: 'email_provisional', sourceName: 'Email templates (sample)' },
];
