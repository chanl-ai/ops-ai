import type { Agent, ApiConfig, Deployment, Evidence, TestCase, GatePolicy, Review, ReviewKind, ReviewStatus, Risk, Tool, Workflow } from '@/lib/types/domain';

/** Demo data for the mock API. Nothing outside lib/api/mock imports this file. */

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

export const CURRENT_USER = { name: 'James Richardson', email: 'j.richardson@northfieldbank.com' };
export const WORKSPACE = { name: 'Northfield Bank', environment: 'Production' };

export const OWNERS = ['Card Services', 'Compliance', 'Fraud Strategy', 'Lending Ops', 'Onboarding', 'Retail Banking', 'Wealth'];
export const MODELS = ['claude-haiku-4-5', 'claude-sonnet-5', 'claude-opus-5-5'];
export const SLA_OPTIONS = ['15 min', '30 min', '1 h', '2 h', '4 h', '8 h', '1 business day', '3 days'];
export const SYSTEMS = ['Branch Scheduler', 'Card Platform', 'Compliance MCP', 'Core Banking', 'Data Hub', 'Equifax', 'Loan Origination', 'Payments Hub', 'The Work Number'];

type WorkflowSeed = Omit<Workflow, 'stepCount' | 'gateCount' | 'openReviews' | 'deploymentCount' | 'pendingPublish'>;

export const WORKFLOWS: WorkflowSeed[] = [
  { id: 'wf_wire', description: 'Scores every large outbound wire and holds the risky ones for an analyst.', owner: 'Fraud Strategy', name: 'Outbound wire review', trigger: 'Wire initiated ≥ $10,000', agentSlugs: ['fraud-sentinel'], runs24h: 1204, reviewed24h: 229, status: 'live', version: 7, updatedAt: ago(60 * 26) },
  { id: 'wf_mortgage', description: 'Takes a mortgage application from intake to pre-approval, with underwriter sign-off on jumbo loans.', owner: 'Lending Ops', name: 'Mortgage pre-approval', trigger: 'Application submitted', agentSlugs: ['mortgage-intake', 'kyb-verifier'], runs24h: 347, reviewed24h: 118, status: 'live', version: 9, updatedAt: ago(60 * 5) },
  { id: 'wf_dispute', description: 'Investigates card disputes and issues provisional credit when policy allows.', owner: 'Card Services', name: 'Card dispute resolution', trigger: 'Dispute filed', agentSlugs: ['dispute-resolver'], runs24h: 412, reviewed24h: 115, status: 'live', version: 4, updatedAt: ago(60 * 24 * 5) },
  { id: 'wf_kyb', description: 'Verifies a business and its owners before the account opens.', owner: 'Onboarding', name: 'Business account onboarding', trigger: 'Business application received', agentSlugs: ['kyb-verifier'], runs24h: 89, reviewed24h: 37, status: 'live', version: 5, updatedAt: ago(60 * 24 * 8) },
  { id: 'wf_branch_chat', description: 'Answers product and branch questions on the website and in the app.', owner: 'Retail Banking', name: 'Branch chat', trigger: 'Chat message', agentSlugs: ['branch-concierge'], runs24h: 795, reviewed24h: 46, status: 'live', version: 3, updatedAt: ago(60 * 30) },
  { id: 'wf_card_inbox', kind: 'email_intake', description: 'Reads the card services mailbox, opens a case per email and drafts the actions for approval.', owner: 'Card Services', name: 'Card services inbox', trigger: 'Email to cardservices@', agentSlugs: ['dispute-resolver'], runs24h: 236, reviewed24h: 141, status: 'live', version: 6, updatedAt: ago(60 * 22) },
  { id: 'wf_lending_inbox', kind: 'email_intake', description: 'Reads the lending servicing mailbox: hardship requests, payoff statements and address changes.', owner: 'Lending Ops', name: 'Lending servicing inbox', trigger: 'Email to lendingservicing@', agentSlugs: ['mortgage-intake'], runs24h: 118, reviewed24h: 77, status: 'live', version: 3, updatedAt: ago(60 * 24 * 3) },
  { id: 'wf_advisor', description: 'Drafts quarterly portfolio notes for each advisor to sign off.', owner: 'Wealth', name: 'Quarterly portfolio review', trigger: 'First business day of the quarter', agentSlugs: ['advisor-copilot'], runs24h: 0, reviewed24h: 0, status: 'draft', version: 1, updatedAt: ago(90) },
];

export const TOOLS: Tool[] = [
  { id: 'tl_1', name: 'get_wire_history', description: 'Wire attempts and MFA results for an account', type: 'http', system: 'Payments Hub', access: 'read', requiresReview: false, enabled: true, calls24h: 2412, errorRate: 0.002, p95Ms: 180, grantedAgentIds: ['ag_fraud'], sampleInput: '{\n  "accountId": "8821-004417",\n  "days": 3\n}' },
  { id: 'tl_2', name: 'place_wire_hold', description: 'Place or release a hold on an outbound wire', type: 'http', system: 'Payments Hub', access: 'money_movement', requiresReview: true, enabled: true, calls24h: 229, errorRate: 0, p95Ms: 240, grantedAgentIds: ['ag_fraud'], sampleInput: '{\n  "wireId": "W-88213",\n  "action": "hold",\n  "hours": 24\n}' },
  { id: 'tl_3', name: 'run_credit_check', description: 'Pull a bureau report and score', type: 'code', system: 'Equifax', access: 'read', requiresReview: false, enabled: true, calls24h: 347, errorRate: 0.011, p95Ms: 1420, grantedAgentIds: ['ag_loan'], sampleInput: '{\n  "applicantId": "APP-40912"\n}' },
  { id: 'tl_4', name: 'verify_employment', description: 'Employment and income verification', type: 'http', system: 'The Work Number', access: 'read', requiresReview: false, enabled: true, calls24h: 301, errorRate: 0.034, p95Ms: 2210, grantedAgentIds: ['ag_loan'], sampleInput: '{\n  "applicantId": "APP-40912",\n  "employer": "Lakeshore Health"\n}' },
  { id: 'tl_5', name: 'issue_preapproval', description: 'Create a pre-approval in the loan system', type: 'http', system: 'Loan Origination', access: 'write', requiresReview: true, enabled: true, calls24h: 229, errorRate: 0.004, p95Ms: 610, grantedAgentIds: ['ag_loan'], sampleInput: '{\n  "applicationId": "APP-40912",\n  "amount": 612000,\n  "rate": 5.24\n}' },
  { id: 'tl_6', name: 'screen_watchlists', description: 'PEP, sanctions and adverse media screening', type: 'mcp', system: 'Compliance MCP', access: 'read', requiresReview: false, enabled: true, calls24h: 267, errorRate: 0, p95Ms: 380, grantedAgentIds: ['ag_kyb'], sampleInput: '{\n  "name": "Aurelia Holdings",\n  "country": "CA"\n}' },
  { id: 'tl_7', name: 'corporate_registry', description: 'Look up a business and its owners', type: 'mcp', system: 'Compliance MCP', access: 'read', requiresReview: false, enabled: true, calls24h: 89, errorRate: 0.022, p95Ms: 940, grantedAgentIds: ['ag_kyb'], sampleInput: '{\n  "registryNumber": "BC1293884"\n}' },
  { id: 'tl_8', name: 'issue_provisional_credit', description: 'Post a provisional credit to a card account', type: 'http', system: 'Card Platform', access: 'money_movement', requiresReview: true, enabled: true, calls24h: 296, errorRate: 0.003, p95Ms: 330, grantedAgentIds: ['ag_dispute'], sampleInput: '{\n  "cardAccount": "4519-****-2231",\n  "amount": 1240.18\n}' },
  { id: 'tl_9', name: 'search_knowledge', description: 'Semantic search with citations', type: 'mcp', system: 'Data Hub', access: 'read', requiresReview: false, enabled: true, calls24h: 4108, errorRate: 0.001, p95Ms: 210, grantedAgentIds: ['ag_fraud', 'ag_loan', 'ag_kyb', 'ag_dispute', 'ag_branch'], sampleInput: '{\n  "query": "new payee wire hold",\n  "collections": ["All bank knowledge"]\n}' },
  { id: 'tl_10', name: 'book_appointment', description: 'Book a branch or advisor appointment', type: 'http', system: 'Branch Scheduler', access: 'write', requiresReview: false, enabled: true, calls24h: 188, errorRate: 0.016, p95Ms: 450, grantedAgentIds: ['ag_branch'], sampleInput: '{\n  "branch": "King & Bay",\n  "slot": "2026-10-06T10:30"\n}' },
  { id: 'tl_11', name: 'get_transactions', description: 'Card transactions for a date range', type: 'http', system: 'Card Platform', access: 'read', requiresReview: false, enabled: true, calls24h: 640, errorRate: 0.005, p95Ms: 260, grantedAgentIds: ['ag_dispute'], sampleInput: '{\n  "cardAccount": "4519-****-2231",\n  "from": "2026-09-01"\n}' },
  { id: 'tl_12', name: 'transfer_funds', description: 'Move funds between a customer’s own accounts', type: 'http', system: 'Core Banking', access: 'money_movement', requiresReview: true, enabled: false, calls24h: 0, errorRate: 0, p95Ms: 0, grantedAgentIds: [], sampleInput: '{\n  "from": "CHQ-1182",\n  "to": "SAV-2219",\n  "amount": 500\n}' },
];

export const AGENTS: Omit<Agent, 'usedIn'>[] = [
  {
    id: 'ag_fraud', guardrails: { redactPii: true, maxToolCallsPerTurn: 6, whenUnsure: 'handoff', blockedTopics: ['Investment advice'] }, name: 'Wire Fraud Sentinel', slug: 'fraud-sentinel', role: 'Scores outbound wires and places holds', model: 'claude-sonnet-5', channels: ['api'], toolIds: ['tl_1', 'tl_2', 'tl_9'], collections: ['Fraud & payments', 'Compliance'], owner: 'Fraud Strategy', status: 'live', version: 7, updatedAt: ago(60 * 26), tasks24h: 1204, autoResolvedRate: 0.81, workflowIds: ['wf_wire'],
    instructions: 'Score every outbound wire of $10,000 or more for account-takeover and mule risk.\n\nAlways place a hold and request review when the payee was added in the last 72 hours and the amount exceeds $50,000.\nNever release a held wire without a confirmed callback to the number on file.\nCite the Wire Fraud Playbook section that drove each decision.',
  },
  {
    id: 'ag_loan', guardrails: { redactPii: true, maxToolCallsPerTurn: 8, whenUnsure: 'ask', blockedTopics: ['Rates not on today’s sheet'] }, name: 'Mortgage Intake', slug: 'mortgage-intake', role: 'Collects and pre-screens mortgage applications', model: 'claude-sonnet-5', channels: ['chat', 'voice'], toolIds: ['tl_3', 'tl_4', 'tl_5', 'tl_9'], collections: ['Lending policy'], owner: 'Lending Ops', status: 'live', version: 9, updatedAt: ago(60 * 5), tasks24h: 347, autoResolvedRate: 0.66, workflowIds: ['wf_mortgage'],
    instructions: 'Collect the documents the Underwriting Guide requires, run credit and employment checks, and draft a pre-approval with rate and term.\n\nSend every application above $500,000 to an underwriter.\nNever quote a rate that is not on today’s rate sheet.',
  },
  { id: 'ag_kyb', guardrails: { redactPii: true, maxToolCallsPerTurn: 8, whenUnsure: 'handoff', blockedTopics: [] }, name: 'KYB Verifier', slug: 'kyb-verifier', role: 'Verifies business owners for account opening', model: 'claude-sonnet-5', channels: ['api', 'email'], toolIds: ['tl_6', 'tl_7', 'tl_9'], collections: ['Compliance'], owner: 'Onboarding', status: 'live', version: 5, updatedAt: ago(60 * 24 * 8), tasks24h: 89, autoResolvedRate: 0.58, workflowIds: ['wf_kyb', 'wf_mortgage'], instructions: 'Verify every beneficial owner above 25% against government ID and the corporate registry. Route any watchlist hit to Enhanced Due Diligence.' },
  { id: 'ag_dispute', guardrails: { redactPii: true, maxToolCallsPerTurn: 6, whenUnsure: 'ask', blockedTopics: [] }, name: 'Card Dispute Resolver', slug: 'dispute-resolver', role: 'Investigates and drafts card dispute outcomes', model: 'claude-sonnet-5', channels: ['chat', 'email'], toolIds: ['tl_8', 'tl_9', 'tl_11'], collections: ['Cards & disputes'], owner: 'Card Services', status: 'live', version: 4, updatedAt: ago(60 * 24 * 5), tasks24h: 412, autoResolvedRate: 0.72, workflowIds: ['wf_dispute'], instructions: 'Match the dispute to a reason code, gather transaction evidence, and propose a provisional credit when the Dispute Rights Guide allows it.' },
  { id: 'ag_branch', guardrails: { redactPii: true, maxToolCallsPerTurn: 4, whenUnsure: 'handoff', blockedTopics: ['Account-specific questions', 'Investment advice'] }, name: 'Branch Concierge', slug: 'branch-concierge', role: 'Books appointments and answers product questions', model: 'claude-haiku-4-5', channels: ['voice', 'chat'], toolIds: ['tl_9', 'tl_10'], collections: ['Retail banking'], owner: 'Retail Banking', status: 'live', version: 12, updatedAt: ago(60 * 30), tasks24h: 795, autoResolvedRate: 0.94, workflowIds: [], instructions: 'Answer questions about accounts, cards and branch services from the Retail banking knowledge base, and book appointments. Hand off anything about a specific account to a person.' },
  { id: 'ag_advisor', guardrails: { redactPii: true, maxToolCallsPerTurn: 6, whenUnsure: 'decline', blockedTopics: [] }, name: 'Advisor Copilot', slug: 'advisor-copilot', role: 'Drafts portfolio review notes for advisors', model: 'claude-opus-5-5', channels: ['chat'], toolIds: [], collections: [], owner: 'Wealth', status: 'draft', version: 1, updatedAt: ago(90), tasks24h: 0, autoResolvedRate: 0, workflowIds: ['wf_advisor'], instructions: '' },
];

export const POLICIES: Omit<GatePolicy, 'workflowName'>[] = [
  { id: 'gp_1', name: 'High-value new payee', workflowId: 'wf_wire', condition: 'amount > 50,000 AND payee.age < 72h', reviewers: 'Fraud Analysts L2', sla: '30 min', onTimeout: 'Hold stays, page on-call', fourEyes: true, hits7d: 214 },
  { id: 'gp_2', name: 'Low agent confidence', workflowId: 'wf_wire', condition: 'agent.confidence < 0.75', reviewers: 'Fraud Analysts L1', sla: '1 h', onTimeout: 'Escalate to L2', fourEyes: false, hits7d: 1188 },
  { id: 'gp_9', name: 'High-risk jurisdiction', workflowId: 'wf_wire', condition: 'payee.country IN high_risk_list', reviewers: 'Fraud Analysts L2', sla: '30 min', onTimeout: 'Hold stays, page on-call', fourEyes: false, hits7d: 58 },
  { id: 'gp_3', name: 'Jumbo pre-approval', workflowId: 'wf_mortgage', condition: 'loan.amount > 500,000', reviewers: 'Underwriters', sla: '4 h', onTimeout: 'Escalate to senior underwriter', fourEyes: false, hits7d: 402 },
  { id: 'gp_4', name: 'Decline appeal', workflowId: 'wf_mortgage', condition: 'application.appeal = true', reviewers: 'Underwriters', sla: '1 business day', onTimeout: 'Notify team lead', fourEyes: false, hits7d: 63 },
  { id: 'gp_5', name: 'Watchlist hit', workflowId: 'wf_kyb', condition: 'screening.pep OR screening.sanctions', reviewers: 'Enhanced Due Diligence', sla: '2 h', onTimeout: 'Onboarding paused', fourEyes: true, hits7d: 21 },
  { id: 'gp_6', name: 'Partial identity match', workflowId: 'wf_kyb', condition: 'owner.nameMatch < 0.90', reviewers: 'KYC Operations', sla: '4 h', onTimeout: 'Return to agent', fourEyes: false, hits7d: 148 },
  { id: 'gp_7', name: 'Credit above threshold', workflowId: 'wf_dispute', condition: 'credit.amount > 1,000', reviewers: 'Card Disputes', sla: '8 h', onTimeout: 'Auto-approve if confidence ≥ 0.9', fourEyes: false, hits7d: 517 },
  { id: 'gp_8', name: 'Goodwill override', workflowId: 'wf_dispute', condition: 'agent.requestsOverride = true', reviewers: 'Card Services Leads', sla: '1 business day', onTimeout: 'Override declined', fourEyes: false, hits7d: 34 },
  { id: 'gp_10', name: 'Advisor sign-off', workflowId: 'wf_advisor', condition: 'always', reviewers: 'Assigned advisor', sla: '3 days', onTimeout: 'Notes not sent', fourEyes: false, hits7d: 0 },
];

export const REVIEWERS = ['James Richardson', 'Maya Okafor', 'Anika Singh', 'Daniel Brooks', 'Priya Shah'];

export const REVIEWER_GROUPS = [...new Set(POLICIES.map((p) => p.reviewers))].sort();

export const ACTION_TOOL: Record<string, string> = {
  wf_wire: 'place_wire_hold',
  wf_mortgage: 'issue_preapproval',
  wf_dispute: 'issue_provisional_credit',
  wf_kyb: 'request_documents',
  wf_advisor: 'send_secure_message',
};

type ReviewSeed = {
  id: string;
  title: string;
  customer: string;
  workflowId: string;
  agentSlug: string;
  kind: ReviewKind;
  risk: Risk;
  confidence: number;
  proposal: string;
  amount?: number;
  policyId: string;
  slaMinutes: number;
  assignee?: string;
  status: ReviewStatus;
  createdMinutesAgo: number;
  reasoning: string[];
  evidence: Evidence[];
  decisionReason?: string;
};

export const REVIEWS: ReviewSeed[] = [
  {
    id: 'REV-3018', title: 'Hold outbound wire to new payee', customer: 'Hartwell Dental Corp', workflowId: 'wf_wire', agentSlug: 'fraud-sentinel', kind: 'approval', risk: 'critical', confidence: 0.91,
    proposal: 'Place a 24-hour hold on wire W-88213 and call the account holder on the number on file', amount: 127800, policyId: 'gp_1', slaMinutes: -32, assignee: 'Maya Okafor', status: 'in_review', createdMinutesAgo: 62,
    reasoning: ['Payee was added 19 hours ago from a device not seen before.', 'Four wire attempts in 12 minutes; three failed MFA.', 'Amount is 340% above the 90-day rolling average.'],
    evidence: [{ kind: 'tool', label: 'get_wire_history', detail: '4 attempts · 3 MFA failures' }, { kind: 'tool', label: 'device_fingerprint', detail: 'New device · foreign IP' }, { kind: 'source', label: 'Wire Fraud Playbook §4.2', detail: 'Holds required for new-payee wires over $50k' }],
  },
  {
    id: 'REV-3017', title: 'PEP match on a director', customer: 'Aurelia Holdings', workflowId: 'wf_kyb', agentSlug: 'kyb-verifier', kind: 'escalation', risk: 'critical', confidence: 0.79,
    proposal: 'Route to Enhanced Due Diligence and pause onboarding', policyId: 'gp_5', slaMinutes: -8, assignee: 'Anika Singh', status: 'in_review', createdMinutesAgo: 128,
    reasoning: ['Director matches a domestic PEP list entry (former municipal councillor).'],
    evidence: [{ kind: 'tool', label: 'screen_watchlists', detail: 'PEP · domestic · score 0.93' }],
  },
  {
    id: 'REV-3021', title: 'Release wire after callback', customer: 'Lin & Moreau LLP', workflowId: 'wf_wire', agentSlug: 'fraud-sentinel', kind: 'approval', risk: 'high', confidence: 0.62,
    proposal: 'Release wire W-88240; the client confirmed it on a callback', amount: 48200, policyId: 'gp_2', slaMinutes: 18, status: 'pending', createdMinutesAgo: 42,
    reasoning: ['Callback reached the registered number and the client confirmed the payment.', 'Payee bank is new for this client but on the trusted correspondent list.'],
    evidence: [{ kind: 'tool', label: 'callback_log', detail: 'Confirmed 09:38 · 2m 14s' }, { kind: 'source', label: 'Correspondent Bank List', detail: 'Payee bank listed, tier 1' }],
  },
  {
    id: 'REV-3009', title: 'Approve pre-approval above the auto limit', customer: 'Sarah Chen', workflowId: 'wf_mortgage', agentSlug: 'mortgage-intake', kind: 'approval', risk: 'medium', confidence: 0.88,
    proposal: 'Issue a pre-approval for $612,000 at 5.24% fixed, 5-year term', amount: 612000, policyId: 'gp_3', slaMinutes: 46, assignee: 'James Richardson', status: 'in_review', createdMinutesAgo: 194,
    reasoning: ['Credit score 742, DTI 31%, employment verified at 4 years.', 'Down payment of 20% from verified savings.'],
    evidence: [{ kind: 'tool', label: 'run_credit_check', detail: 'Score 742 · 0 delinquencies' }, { kind: 'tool', label: 'verify_employment', detail: 'Confirmed · $168k salary' }, { kind: 'source', label: 'Mortgage Underwriting Guide v4.2', detail: 'GDS ≤ 39%, TDS ≤ 44%' }],
  },
  {
    id: 'REV-3015', title: 'Verify owner with a partial ID match', customer: 'Northgate Logistics Inc.', workflowId: 'wf_kyb', agentSlug: 'kyb-verifier', kind: 'exception', risk: 'high', confidence: 0.67,
    proposal: 'Request a second government ID from owner 2 before opening the account', policyId: 'gp_6', slaMinutes: 95, status: 'pending', createdMinutesAgo: 145,
    reasoning: ['Owner 2 is "Abdul Rahman Q." on the registry and "Abdulrahman Qureshi" on the passport.', 'Date of birth and address match.'],
    evidence: [{ kind: 'tool', label: 'corporate_registry', detail: '3 owners · 1 partial match' }, { kind: 'tool', label: 'id_verify', detail: 'Passport valid · 87% name match' }],
  },
  {
    id: 'REV-3012', title: 'Re-evaluate a declined application', customer: 'Daniel Okoye', workflowId: 'wf_mortgage', agentSlug: 'mortgage-intake', kind: 'exception', risk: 'medium', confidence: 0.54,
    proposal: 'Re-score with the updated income documents; DTI falls from 52% to 38%', amount: 384000, policyId: 'gp_4', slaMinutes: 210, status: 'pending', createdMinutesAgo: 236,
    reasoning: ['New T4 shows a raise effective January.', 'The earlier decline was driven only by DTI.'],
    evidence: [{ kind: 'tool', label: 'extract_document', detail: 'T4 2025 · $142,000' }, { kind: 'source', label: 'Appeals Policy', detail: 'One re-score allowed within 30 days' }],
  },
  {
    id: 'REV-3020', title: 'Provisional credit on a duplicate charge', customer: 'Priya Natarajan', workflowId: 'wf_dispute', agentSlug: 'dispute-resolver', kind: 'approval', risk: 'low', confidence: 0.94,
    proposal: 'Issue a provisional credit of $1,240.18 and open a chargeback', amount: 1240.18, policyId: 'gp_7', slaMinutes: 380, status: 'pending', createdMinutesAgo: 50,
    reasoning: ['Two identical settlements from the same merchant 41 seconds apart.'],
    evidence: [{ kind: 'tool', label: 'get_transactions', detail: '2 matching settlements' }, { kind: 'source', label: 'Dispute Rights Guide', detail: 'Duplicate processing · reason 12.6' }],
  },
  {
    id: 'REV-3019', title: 'Waive a fee outside policy', customer: 'Marcus Webb', workflowId: 'wf_dispute', agentSlug: 'dispute-resolver', kind: 'policy_override', risk: 'low', confidence: 0.71,
    proposal: 'Waive the $45 dispute investigation fee as a goodwill gesture', amount: 45, policyId: 'gp_8', slaMinutes: 520, status: 'pending', createdMinutesAgo: 63,
    reasoning: ['Customer has a 14-year tenure and no prior waivers.'],
    evidence: [{ kind: 'source', label: 'Fee Waiver Policy', detail: 'One goodwill waiver per 12 months' }],
  },
  {
    id: 'REV-3022', title: 'Hold wire with mismatched payee name', customer: 'Brennan Orthodontics', workflowId: 'wf_wire', agentSlug: 'fraud-sentinel', kind: 'approval', risk: 'high', confidence: 0.83,
    proposal: 'Hold wire W-88251 until the payee name matches the receiving account', amount: 73400, policyId: 'gp_1', slaMinutes: 24, status: 'pending', createdMinutesAgo: 6,
    reasoning: ['Receiving bank returned a name-check mismatch.', 'Payee added 2 days ago.'],
    evidence: [{ kind: 'tool', label: 'payee_name_check', detail: 'Mismatch · 41% similarity' }],
  },
  {
    id: 'REV-3023', title: 'Approve pre-approval above the auto limit', customer: 'Tomás Alvarez', workflowId: 'wf_mortgage', agentSlug: 'mortgage-intake', kind: 'approval', risk: 'medium', confidence: 0.86,
    proposal: 'Issue a pre-approval for $548,000 at 5.19% fixed, 3-year term', amount: 548000, policyId: 'gp_3', slaMinutes: 232, status: 'pending', createdMinutesAgo: 8,
    reasoning: ['Credit score 768, DTI 34%.', 'Self-employed; two years of NOAs on file.'],
    evidence: [{ kind: 'tool', label: 'run_credit_check', detail: 'Score 768' }, { kind: 'source', label: 'Mortgage Underwriting Guide v4.2', detail: 'Self-employed income: 2-year average' }],
  },
  {
    id: 'REV-3024', title: 'Provisional credit on a non-delivery claim', customer: 'Grace Kim', workflowId: 'wf_dispute', agentSlug: 'dispute-resolver', kind: 'approval', risk: 'low', confidence: 0.9,
    proposal: 'Issue a provisional credit of $1,089.00 and open a chargeback', amount: 1089, policyId: 'gp_7', slaMinutes: 455, status: 'pending', createdMinutesAgo: 25,
    reasoning: ['Merchant tracking shows the parcel returned to sender.'],
    evidence: [{ kind: 'tool', label: 'get_transactions', detail: '1 settlement · $1,089.00' }],
  },
  {
    id: 'REV-3004', title: 'Hold wire to a flagged jurisdiction', customer: 'Coastal Imports Ltd.', workflowId: 'wf_wire', agentSlug: 'fraud-sentinel', kind: 'approval', risk: 'high', confidence: 0.86,
    proposal: 'Hold wire W-88102 and request purpose-of-payment documents', amount: 64500, policyId: 'gp_9', slaMinutes: 0, assignee: 'Maya Okafor', status: 'approved', createdMinutesAgo: 300,
    reasoning: ['Destination country is on the internal high-risk list.'], evidence: [{ kind: 'source', label: 'Jurisdiction Risk List', detail: 'Tier 2' }], decisionReason: 'Held as proposed.',
  },
  {
    id: 'REV-3002', title: 'Approve pre-approval above the auto limit', customer: 'Elena Vasquez', workflowId: 'wf_mortgage', agentSlug: 'mortgage-intake', kind: 'approval', risk: 'medium', confidence: 0.83,
    proposal: 'Issue a pre-approval for $540,000 at 5.19% fixed', amount: 540000, policyId: 'gp_3', slaMinutes: 0, assignee: 'James Richardson', status: 'rejected', createdMinutesAgo: 340,
    reasoning: ['Employment verified.'], evidence: [{ kind: 'tool', label: 'verify_employment', detail: 'On probation until December' }],
    decisionReason: 'Applicant is on probation until December. Re-apply once permanent.',
  },
  {
    id: 'REV-3006', title: 'Re-run KYB with the corrected registry number', customer: 'Brightline Studio', workflowId: 'wf_kyb', agentSlug: 'kyb-verifier', kind: 'exception', risk: 'low', confidence: 0.6,
    proposal: 'Retry the registry lookup', policyId: 'gp_6', slaMinutes: 0, assignee: 'Anika Singh', status: 'returned', createdMinutesAgo: 380,
    reasoning: ['Registry lookup failed on a transposed digit.'], evidence: [{ kind: 'tool', label: 'corporate_registry', detail: 'Not found' }],
    decisionReason: 'Correct number is BC1293884; retry with that.',
  },
];

export const THROUGHPUT_7D = [
  { day: 'Sep 27', completedByAgent: 1890, sentToReview: 402 },
  { day: 'Sep 28', completedByAgent: 1640, sentToReview: 355 },
  { day: 'Sep 29', completedByAgent: 2210, sentToReview: 488 },
  { day: 'Sep 30', completedByAgent: 2380, sentToReview: 512 },
  { day: 'Oct 1', completedByAgent: 2290, sentToReview: 470 },
  { day: 'Oct 2', completedByAgent: 2450, sentToReview: 503 },
  { day: 'Oct 3', completedByAgent: 2348, sentToReview: 499 },
];

export const reviewCreatedAt = ago;

export type DeploymentSeed = Omit<Deployment, 'workflowName' | 'latestVersion' | 'api'> & { api?: ApiConfig };

export const DEPLOYMENTS: DeploymentSeed[] = [
  { id: 'dp_widget', name: 'Website chat', workflowId: 'wf_branch_chat', channel: 'widget', environment: 'production', version: 3, status: 'active', traffic24h: 583, errors24h: 2, createdAt: ago(60 * 24 * 40), updatedAt: ago(60 * 30), widget: { title: 'Ask Northfield', welcomeMessage: 'Hi! Ask about accounts, cards or branch hours.', allowedDomains: ['www.northfieldbank.com', 'northfieldbank.com'], position: 'right' } },
  { id: 'dp_widget_stg', name: 'Website chat (staging)', workflowId: 'wf_branch_chat', channel: 'widget', environment: 'staging', version: 3, status: 'active', traffic24h: 41, errors24h: 0, createdAt: ago(60 * 24 * 40), updatedAt: ago(60 * 30), widget: { title: 'Ask Northfield (staging)', welcomeMessage: 'Staging build.', allowedDomains: ['staging.northfieldbank.com'], position: 'right' } },
  { id: 'dp_app_api', name: 'Mobile app chat', workflowId: 'wf_branch_chat', channel: 'api', environment: 'production', version: 3, status: 'active', traffic24h: 212, errors24h: 1, createdAt: ago(60 * 24 * 21), updatedAt: ago(60 * 30), api: { rateLimitPerMinute: 600, keyPrefix: 'nfb_live_7Qx' } },
  { id: 'dp_wire_api', name: 'Payments Hub events', workflowId: 'wf_wire', channel: 'api', environment: 'production', version: 7, status: 'active', traffic24h: 1204, errors24h: 3, createdAt: ago(60 * 24 * 90), updatedAt: ago(60 * 26), api: { rateLimitPerMinute: 1200, keyPrefix: 'nfb_live_Wr2' } },
  { id: 'dp_dispute_email', name: 'Disputes inbox', workflowId: 'wf_dispute', channel: 'email', environment: 'production', version: 3, status: 'active', traffic24h: 188, errors24h: 0, createdAt: ago(60 * 24 * 60), updatedAt: ago(60 * 24 * 9), email: { inboundAddress: 'disputes@northfieldbank.com', replyFrom: 'Card Services <cards@northfieldbank.com>', repliesNeedReview: true } },
  { id: 'dp_card_mailbox', name: 'Card services mailbox', workflowId: 'wf_card_inbox', channel: 'email', environment: 'production', version: 6, status: 'active', traffic24h: 236, errors24h: 0, createdAt: ago(60 * 24 * 45), updatedAt: ago(60 * 22), email: { inboundAddress: 'cardservices@northfieldbank.com', replyFrom: 'Northfield Card Services <cardservices@northfieldbank.com>', repliesNeedReview: true, folders: ['Inbox'], securityScan: true, archive: true, sync: { status: 'healthy', lastMessageAt: ago(4), messages24h: 236 } } },
  { id: 'dp_lending_mailbox', name: 'Lending servicing mailbox', workflowId: 'wf_lending_inbox', channel: 'email', environment: 'production', version: 3, status: 'active', traffic24h: 118, errors24h: 2, createdAt: ago(60 * 24 * 20), updatedAt: ago(60 * 24 * 3), email: { inboundAddress: 'lendingservicing@northfieldbank.com', replyFrom: 'Northfield Lending <lendingservicing@northfieldbank.com>', repliesNeedReview: true, folders: ['Inbox', 'Hardship'], securityScan: true, archive: true, sync: { status: 'error', lastMessageAt: ago(95), messages24h: 118, error: 'Microsoft Graph returned 401: the mailbox consent expired. Reconnect to resume.' } } },
  { id: 'dp_mortgage_api', name: 'Broker portal', workflowId: 'wf_mortgage', channel: 'api', environment: 'production', version: 9, status: 'paused', traffic24h: 0, errors24h: 0, createdAt: ago(60 * 24 * 30), updatedAt: ago(60 * 4), api: { rateLimitPerMinute: 300, keyPrefix: 'nfb_live_Mg9' } },
];

const tc = (id: string, workflowId: string, name: string, input: string, expect: TestCase['expect'], source: TestCase['source'] = 'manual'): TestCase => ({ id, workflowId, name, input, expect, source, createdAt: ago(60 * 24 * 7) });

export const TEST_CASES: TestCase[] = [
  tc('tc_w1', 'wf_wire', 'New payee, $127,800', '{ "amount": 127800, "payeeAgeHours": 19, "mfaFailures": 3 }', { pauses: 'yes', callsTool: 'get_wire_history' }),
  tc('tc_w2', 'wf_wire', 'Known payee, $12,000', '{ "amount": 12000, "payeeAgeHours": 4000 }', { pauses: 'no', callsTool: 'get_wire_history' }),
  tc('tc_w3', 'wf_wire', 'High-risk jurisdiction', '{ "amount": 64500, "country": "tier2" }', { pauses: 'yes' }, 'run'),
  tc('tc_w4', 'wf_wire', 'Callback confirmed release', '{ "amount": 48200, "callback": "confirmed" }', { pauses: 'yes' }, 'run'),
  tc('tc_w5', 'wf_wire', 'Mule pattern', '{ "amount": 9900, "repeats": 6 }', { callsTool: 'place_wire_hold' }, 'csv'),
  tc('tc_d1', 'wf_dispute', 'Duplicate charge $1,240', '{ "reason": "duplicate", "amount": 1240.18 }', { pauses: 'yes', callsTool: 'get_transactions' }),
  tc('tc_d2', 'wf_dispute', 'Small duplicate $38', '{ "reason": "duplicate", "amount": 38 }', { pauses: 'no', replyContains: 'credit' }),
  tc('tc_d3', 'wf_dispute', 'Goodwill fee waiver', '{ "reason": "fee", "amount": 45 }', { pauses: 'yes' }, 'run'),
  tc('tc_c1', 'wf_branch_chat', 'Branch hours', 'What time does King & Bay open on Saturday?', { pauses: 'no', callsTool: 'search_knowledge', replyContains: 'Saturday' }),
  tc('tc_c2', 'wf_branch_chat', 'Book an appointment', 'Can I see a mortgage advisor Tuesday morning?', { callsTool: 'book_appointment' }),
  tc('tc_c3', 'wf_branch_chat', 'Account balance (must hand off)', 'What is my chequing balance?', { replyContains: 'person' }, 'run'),
  tc('tc_m1', 'wf_mortgage', 'Jumbo pre-approval', '{ "amount": 612000, "score": 742 }', { pauses: 'yes', callsTool: 'run_credit_check' }),
  tc('tc_m2', 'wf_mortgage', 'Standard pre-approval', '{ "amount": 380000, "score": 760 }', { pauses: 'no', callsTool: 'issue_preapproval' }),
];
