import type { ToolAccess } from '@/lib/types/domain';
import type {
  BindingSource,
  CatalogItem,
  CredentialKind,
  DiscoveredOperation,
  Environment,
  HttpMethod,
  ModuleType,
  OperationChange,
  SchemaField,
  SubjectBinding,
} from '@/lib/types/tool-modules';

/** Seed times are relative to page load; the mock only runs in the browser. */
export const DAY = 86_400_000;
export const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();
export const inDays = (d: number) => new Date(Date.now() + d * DAY).toISOString();

export const f = (name: string, type: SchemaField['type'], required: boolean, description?: string, extra?: Partial<SchemaField>): SchemaField => ({ name, type, required, description, ...extra });
const bind = (arg: string, bindTo: BindingSource, mode: SubjectBinding['mode'] = 'equals', required = true): SubjectBinding => ({ arg, bindTo, mode, required });

/** Operation facts the module manifest holds. Description, access and call stats live on the grantable tool record. */
export interface OperationSeed {
  name: string;
  /** Only for operations with no tool record in the fixtures. */
  tool?: { description: string; access: ToolAccess; calls24h: number; errorRate: number; p95Ms: number; enabled?: boolean };
  method?: HttpMethod;
  path?: string;
  input: SchemaField[];
  binding: SubjectBinding | null;
  masked?: string[];
  rate?: number;
  amountMax?: number;
  requiresApproval?: boolean;
  /** Canned, schema-valid output for test mode. */
  stub: Record<string, unknown>;
}

export interface VersionSeed {
  version: string;
  daysAgo: number;
  by: string;
  note: string;
  changes: OperationChange[];
  pinnedBy?: string[];
}

export interface ApprovalSeed {
  workflowId: string;
  operations: string[];
  environment?: Environment;
  status?: 'requested' | 'approved' | 'revoked';
  /** Days until expiry; negative for already expired. */
  expiresIn?: number;
  requestedBy?: string;
  decidedBy?: string;
  justification: string;
  constraints?: string;
  ageDays?: number;
}

export interface ModuleSeed {
  id: string;
  name: string;
  displayName: string;
  system: string;
  description: string;
  type: ModuleType;
  status?: 'draft' | 'in_review' | 'published';
  ownerTeam: string;
  ownerContacts: string[];
  endpoint: string;
  auth: CredentialKind | 'none';
  authHeader?: string;
  timeoutMs: number;
  egressHosts: string[];
  dataClassification: 'public' | 'internal' | 'confidential' | 'restricted';
  catalogId?: string;
  reachable?: boolean;
  drift?: boolean;
  operations: OperationSeed[];
  versions: VersionSeed[];
  approvals: ApprovalSeed[];
  /** Days until each environment's credential must be rotated. */
  rotate?: Partial<Record<Environment, number>>;
  reviewer?: string;
  findings?: string[];
  /** Security review of the current major is still open. */
  reviewPending?: boolean;
}

const ch = (operation: string, kind: OperationChange['kind'], detail: string, major = false): OperationChange => ({ operation, kind, detail, major });
const SECURITY = 'Nadia Petrov';

export const MODULE_SEEDS: ModuleSeed[] = [
  {
    id: 'mod_core_banking',
    name: 'core-banking',
    displayName: 'Core banking',
    system: 'Core Banking',
    description: 'Loan and deposit accounts, customer profiles and servicing actions in the core ledger.',
    type: 'openapi',
    ownerTeam: 'Core Banking Platform',
    ownerContacts: ['Daniel Brooks', 'Lena Fischer'],
    endpoint: 'https://corebanking.api.northfield.internal/v3',
    auth: 'oauth_client_credentials',
    timeoutMs: 8000,
    egressHosts: ['corebanking.api.northfield.internal'],
    dataClassification: 'restricted',
    catalogId: 'cat_core_banking',
    rotate: { production: 41, test: 12 },
    reviewer: SECURITY,
    findings: ['Customer SIN and date of birth masked in every response', 'Writes require idempotency keys', 'Transfers capped at $2,500 per call'],
    operations: [
      {
        name: 'get_loan_account',
        tool: { description: 'Balance, rate, next payment and arrears for a loan account', access: 'read', calls24h: 214, errorRate: 0.004, p95Ms: 310 },
        method: 'GET',
        path: '/loans/{loanAccountId}',
        input: [f('loanAccountId', 'string', true, 'Loan account number', { example: 'LN-0048213' }), f('include', 'array', false, 'Extra sections: schedule, arrears, collateral')],
        binding: bind('loanAccountId', 'case.account'),
        masked: ['borrower.sin', 'borrower.dateOfBirth'],
        rate: 120,
        stub: { loanAccountId: 'LN-0048213', product: 'Fixed 5-year mortgage', balance: 412_880.14, rate: 4.89, nextPayment: { date: '2026-10-15', amount: 2318.4 }, arrears: 0, borrower: { name: 'Marcus Webb', sin: '[redacted]', dateOfBirth: '[redacted]' } },
      },
      {
        name: 'get_customer_profile',
        tool: { description: 'Name, contact details and products held by a customer', access: 'read', calls24h: 188, errorRate: 0.002, p95Ms: 240 },
        method: 'GET',
        path: '/customers/{customerId}',
        input: [f('customerId', 'string', true, 'Customer number', { example: 'CUS-118842' })],
        binding: bind('customerId', 'case.customerId'),
        masked: ['sin', 'dateOfBirth'],
        rate: 120,
        stub: { customerId: 'CUS-118842', name: 'Marcus Webb', email: 'marcus.webb@example.com', phone: '+1 416 555 0143', sin: '[redacted]', dateOfBirth: '[redacted]', products: ['Mortgage LN-0048213', 'Chequing CHQ-1182'] },
      },
      {
        name: 'update_address',
        tool: { description: 'Change a customer’s mailing address', access: 'write', calls24h: 41, errorRate: 0.008, p95Ms: 520 },
        method: 'PATCH',
        path: '/customers/{customerId}/address',
        input: [f('customerId', 'string', true, 'Customer number'), f('line1', 'string', true, 'Street address'), f('line2', 'string', false), f('city', 'string', true), f('province', 'string', true, undefined, { enum: ['AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'ON', 'PE', 'QC', 'SK'] }), f('postalCode', 'string', true, undefined, { format: 'A1A 1A1' })],
        binding: bind('customerId', 'case.customerId'),
        rate: 30,
        stub: { updated: true, effective: '2026-10-04', previousAddressRetained: true },
      },
      {
        name: 'apply_payment_deferral',
        tool: { description: 'Defer one or more loan payments under the hardship program', access: 'write', calls24h: 9, errorRate: 0, p95Ms: 780 },
        method: 'POST',
        path: '/loans/{loanAccountId}/deferrals',
        input: [f('loanAccountId', 'string', true), f('payments', 'integer', true, 'Number of payments to defer (1–3)'), f('reasonCode', 'string', true, undefined, { enum: ['job_loss', 'illness', 'disaster', 'other'] })],
        binding: bind('loanAccountId', 'case.account'),
        rate: 10,
        stub: { deferralId: 'DEF-22184', payments: 2, resumesOn: '2027-01-15', interestCapitalised: 1904.22 },
      },
      {
        name: 'get_payoff_statement',
        tool: { description: 'Payoff amount and per-diem interest for a loan as of a date', access: 'read', calls24h: 23, errorRate: 0.011, p95Ms: 920 },
        method: 'GET',
        path: '/loans/{loanAccountId}/payoff',
        input: [f('loanAccountId', 'string', true), f('asOf', 'string', true, 'Payoff date', { format: 'date' })],
        binding: bind('loanAccountId', 'case.account'),
        rate: 60,
        stub: { loanAccountId: 'LN-0048213', asOf: '2026-10-31', payoff: 411_960.02, perDiem: 55.31, prepaymentCharge: 3120 },
      },
      {
        name: 'transfer_funds',
        method: 'POST',
        path: '/transfers',
        input: [f('fromAccount', 'string', true), f('toAccount', 'string', true), f('amount', 'number', true, 'CAD'), f('memo', 'string', false)],
        binding: bind('fromAccount', 'case.customerId', 'within'),
        rate: 5,
        amountMax: 2500,
        stub: { transferId: 'TRF-58812', status: 'posted', amount: 500 },
      },
    ],
    versions: [
      { version: '2.8.4', daysAgo: 210, by: 'Daniel Brooks', note: 'Timeout raised to 8 s for statement calls', changes: [ch('get_loan_account', 'settings', 'Timeout 5 s → 8 s')] },
      { version: '3.0.0', daysAgo: 96, by: 'Daniel Brooks', note: 'Hardship deferrals and transfers', changes: [ch('apply_payment_deferral', 'added', 'New write operation', true), ch('transfer_funds', 'added', 'New money movement operation, capped at $2,500', true)] },
      { version: '3.1.0', daysAgo: 52, by: 'Lena Fischer', note: 'Payoff statements', changes: [ch('get_payoff_statement', 'added', 'New read operation; within major 3 because the module review covered statement reads', false)] },
      { version: '3.2.0', daysAgo: 21, by: 'Lena Fischer', note: 'Address line 2 and postal code format', changes: [ch('update_address', 'schema_changed', 'Adds optional line2; postalCode now validated as A1A 1A1')], pinnedBy: ['wf_card_inbox'] },
      { version: '3.2.1', daysAgo: 6, by: 'Daniel Brooks', note: 'Masks date of birth in profile responses', changes: [ch('get_customer_profile', 'settings', 'Masks dateOfBirth')], pinnedBy: ['wf_lending_inbox'] },
    ],
    approvals: [
      { workflowId: 'wf_lending_inbox', operations: ['get_loan_account', 'get_customer_profile', 'get_payoff_statement', 'apply_payment_deferral', 'update_address'], expiresIn: 3, decidedBy: 'Daniel Brooks', justification: 'Lending servicing inbox: hardship deferrals, payoff statements and address changes', constraints: 'Deferrals: at most 3 payments per request' },
      { workflowId: 'wf_card_inbox', operations: ['get_customer_profile', 'update_address'], expiresIn: 148, decidedBy: 'Lena Fischer', justification: 'Address changes requested by email to card services' },
      { workflowId: 'wf_dispute', operations: ['get_customer_profile'], status: 'requested', expiresIn: 180, requestedBy: 'Grace Liu', justification: 'Confirm the cardholder’s contact details before posting a provisional credit', ageDays: 2 },
    ],
  },
  {
    id: 'mod_card_platform',
    name: 'card-platform',
    displayName: 'Card platform',
    system: 'Card Platform',
    description: 'Card transactions, provisional credits and fee adjustments.',
    type: 'openapi',
    ownerTeam: 'Card Services',
    ownerContacts: ['Grace Liu'],
    endpoint: 'https://cards.api.northfield.internal/v2',
    auth: 'mtls',
    timeoutMs: 6000,
    egressHosts: ['cards.api.northfield.internal'],
    dataClassification: 'restricted',
    rotate: { production: 9, test: 70 },
    reviewer: SECURITY,
    findings: ['Card numbers returned masked to the last four digits', 'Provisional credit capped at $5,000 per call and needs four eyes'],
    operations: [
      { name: 'get_transactions', method: 'GET', path: '/accounts/{cardAccount}/transactions', input: [f('cardAccount', 'string', true), f('from', 'string', true, undefined, { format: 'date' }), f('to', 'string', false, undefined, { format: 'date' })], binding: bind('cardAccount', 'case.account'), masked: ['transactions[].pan'], rate: 120, stub: { cardAccount: '4519-••••-2231', transactions: [{ id: 'TX-90812', merchant: 'Lakeshore Outfitters', amount: 1240.18, posted: '2026-09-21', pan: '[redacted]' }] } },
      { name: 'issue_provisional_credit', method: 'POST', path: '/accounts/{cardAccount}/provisional-credits', input: [f('cardAccount', 'string', true), f('amount', 'number', true, 'CAD'), f('disputeId', 'string', true)], binding: bind('cardAccount', 'case.account'), rate: 20, amountMax: 5000, stub: { creditId: 'PC-31877', amount: 1240.18, status: 'posted', reversibleUntil: '2026-12-03' } },
      {
        name: 'waive_fee',
        tool: { description: 'Reverse a card fee', access: 'write', calls24h: 64, errorRate: 0.006, p95Ms: 290 },
        method: 'POST',
        path: '/accounts/{cardAccount}/fee-reversals',
        input: [f('cardAccount', 'string', true), f('feeId', 'string', true), f('amount', 'number', true, 'CAD')],
        binding: bind('cardAccount', 'case.account'),
        rate: 30,
        stub: { reversalId: 'FR-7781', amount: 39, status: 'posted' },
      },
    ],
    versions: [
      { version: '2.3.0', daysAgo: 140, by: 'Grace Liu', note: 'Fee reversals', changes: [ch('waive_fee', 'added', 'New write operation', true)] },
      { version: '2.4.0', daysAgo: 33, by: 'Grace Liu', note: 'Dispute id on provisional credits', changes: [ch('issue_provisional_credit', 'schema_changed', 'disputeId now required')], pinnedBy: ['wf_dispute', 'wf_card_inbox'] },
    ],
    approvals: [
      { workflowId: 'wf_dispute', operations: ['get_transactions', 'issue_provisional_credit'], expiresIn: 112, decidedBy: 'Grace Liu', justification: 'Dispute investigation and provisional credit under the Dispute Rights Guide', constraints: 'Provisional credit up to $5,000' },
      { workflowId: 'wf_card_inbox', operations: ['get_transactions', 'issue_provisional_credit', 'waive_fee'], expiresIn: 11, decidedBy: 'Grace Liu', justification: 'Card services inbox: disputes and fee complaints by email', constraints: 'Fee reversals up to $100' },
    ],
  },
  {
    id: 'mod_m365_mail',
    name: 'm365-mail',
    displayName: 'Microsoft 365 mail',
    system: 'Outbound mail',
    description: 'Reads mail threads and sends replies from the bank’s shared mailboxes.',
    type: 'openapi',
    ownerTeam: 'Messaging Platform',
    ownerContacts: ['Omar Siddiqui'],
    endpoint: 'https://graph.microsoft.com/v1.0',
    auth: 'oauth_client_credentials',
    timeoutMs: 10000,
    egressHosts: ['graph.microsoft.com', 'login.microsoftonline.com'],
    dataClassification: 'confidential',
    catalogId: 'cat_m365_mail',
    rotate: { production: -3, test: 200 },
    reviewer: SECURITY,
    findings: ['Replies only to the case requester: recipient bound from the authenticated sender', 'Application access policy limits the app to the two shared mailboxes'],
    operations: [
      { name: 'get_thread', tool: { description: 'Messages in the case’s email thread', access: 'read', calls24h: 311, errorRate: 0.003, p95Ms: 410 }, method: 'GET', path: '/users/{mailbox}/messages/{messageId}', input: [f('mailbox', 'string', true), f('messageId', 'string', true)], binding: bind('messageId', 'case.id'), rate: 240, stub: { subject: 'Change of address', from: 'm.webb@example.com', messages: 2 } },
      {
        name: 'send_reply',
        tool: { description: 'Reply to the customer on the case thread', access: 'write', calls24h: 187, errorRate: 0.005, p95Ms: 640 },
        method: 'POST',
        path: '/users/{mailbox}/messages/{messageId}/reply',
        input: [f('mailbox', 'string', true), f('messageId', 'string', true), f('to', 'string', true, 'Recipient', { format: 'email' }), f('body', 'string', true, 'Reply text')],
        binding: bind('to', 'case.requesterEmail'),
        rate: 60,
        stub: { sent: true, messageId: 'AAMkAGI2…', to: 'm.webb@example.com' },
      },
    ],
    versions: [
      { version: '1.0.0', daysAgo: 120, by: 'Omar Siddiqui', note: 'First version', changes: [ch('get_thread', 'added', 'New read operation', true), ch('send_reply', 'added', 'New write operation', true)] },
      { version: '1.1.0', daysAgo: 18, by: 'Omar Siddiqui', note: 'Plain-text replies', changes: [ch('send_reply', 'settings', 'Sends plain text when the thread is plain text')], pinnedBy: ['wf_card_inbox', 'wf_lending_inbox'] },
    ],
    approvals: [
      { workflowId: 'wf_card_inbox', operations: ['get_thread', 'send_reply'], expiresIn: 205, decidedBy: 'Omar Siddiqui', justification: 'Reply to customers who wrote to card services' },
      { workflowId: 'wf_lending_inbox', operations: ['get_thread', 'send_reply'], expiresIn: 190, decidedBy: 'Omar Siddiqui', justification: 'Reply to customers who wrote to lending servicing' },
    ],
  },
  {
    id: 'mod_salesforce',
    name: 'salesforce-crm',
    displayName: 'Salesforce',
    system: 'Salesforce',
    description: 'Contacts, service cases and activity history in the bank’s Salesforce org, through its hosted MCP server.',
    type: 'mcp',
    ownerTeam: 'CRM Platform',
    ownerContacts: ['Rafael Costa'],
    endpoint: 'https://northfield.my.salesforce.com/services/mcp/v1',
    auth: 'oauth_client_credentials',
    timeoutMs: 8000,
    egressHosts: ['northfield.my.salesforce.com'],
    dataClassification: 'confidential',
    catalogId: 'cat_salesforce',
    drift: true,
    rotate: { production: 88 },
    reviewer: SECURITY,
    findings: ['Snapshot of 3 tools reviewed; the server must not add tools without a new review'],
    operations: [
      { name: 'find_contact', tool: { description: 'Find a contact by email or phone', access: 'read', calls24h: 96, errorRate: 0.01, p95Ms: 520 }, input: [f('email', 'string', false, undefined, { format: 'email' }), f('phone', 'string', false)], binding: null, masked: ['contact.birthdate'], rate: 120, stub: { contact: { id: '003Qy00000Fh2', name: 'Marcus Webb', owner: 'Lending Servicing', birthdate: '[redacted]' } } },
      { name: 'get_case_history', tool: { description: 'Service cases and notes for a contact', access: 'read', calls24h: 74, errorRate: 0.004, p95Ms: 610 }, input: [f('contactId', 'string', true)], binding: bind('contactId', 'case.customerId'), rate: 120, stub: { cases: [{ number: '00418812', subject: 'Payment deferral', status: 'Closed' }] } },
      { name: 'log_activity', tool: { description: 'Log a call or email against a contact', access: 'write', calls24h: 0, errorRate: 0, p95Ms: 0 }, input: [f('contactId', 'string', true), f('subject', 'string', true), f('notes', 'string', true)], binding: bind('contactId', 'case.customerId'), rate: 60, requiresApproval: false, stub: { activityId: '00TQy000002rT', logged: true } },
    ],
    versions: [{ version: '1.2.0', daysAgo: 44, by: 'Rafael Costa', note: 'Activity logging', changes: [ch('log_activity', 'added', 'New write operation', true)], pinnedBy: ['wf_card_inbox'] }],
    approvals: [
      { workflowId: 'wf_card_inbox', operations: ['find_contact', 'get_case_history'], expiresIn: 230, decidedBy: 'Rafael Costa', justification: 'Show the agent prior service cases for the sender' },
      { workflowId: 'wf_lending_inbox', operations: ['find_contact', 'log_activity'], status: 'requested', expiresIn: 180, requestedBy: 'Maya Okafor', justification: 'Log each handled email on the contact so branches see it', ageDays: 1 },
    ],
  },
  {
    id: 'mod_case_mgmt',
    name: 'case-management',
    displayName: 'Case management system',
    system: 'Case management system',
    description: 'The bank’s case management system: signed agreements, statements and identity documents held on customer cases.',
    type: 'mcp',
    status: 'in_review',
    ownerTeam: 'Enterprise Data',
    ownerContacts: ['Anika Singh'],
    endpoint: 'https://casemgmt.northfield.internal/mcp',
    auth: 'mtls',
    timeoutMs: 12000,
    egressHosts: ['casemgmt.northfield.internal'],
    dataClassification: 'restricted',
    catalogId: 'cat_case_mgmt',
    rotate: { production: 160, test: 160 },
    reviewPending: true,
    operations: [
      { name: 'search_documents', tool: { description: 'Search the document store by customer and type', access: 'read', calls24h: 0, errorRate: 0, p95Ms: 0 }, input: [f('customerId', 'string', true), f('type', 'string', false, undefined, { enum: ['agreement', 'statement', 'id_document'] })], binding: bind('customerId', 'case.customerId'), rate: 60, stub: { documents: [{ id: 'DOC-77120', type: 'agreement', title: 'Mortgage commitment', signed: '2021-04-02' }] } },
      { name: 'get_document', tool: { description: 'Fetch one document’s text and metadata', access: 'read', calls24h: 0, errorRate: 0, p95Ms: 0 }, input: [f('documentId', 'string', true), f('customerId', 'string', true)], binding: bind('customerId', 'case.customerId'), masked: ['text.sin'], rate: 60, stub: { id: 'DOC-77120', pages: 14, text: 'This commitment… SIN [redacted]' } },
    ],
    versions: [{ version: '0.9.0', daysAgo: 4, by: 'Anika Singh', note: 'First version for review', changes: [ch('search_documents', 'added', 'New read operation', true), ch('get_document', 'added', 'New read operation', true)] }],
    approvals: [],
  },
  {
    id: 'mod_sharepoint',
    name: 'sharepoint-policies',
    displayName: 'SharePoint policies',
    system: 'SharePoint',
    description: 'Read-only access to the policy and procedure sites.',
    type: 'mcp',
    ownerTeam: 'Digital Workplace',
    ownerContacts: ['Tom Haddad'],
    endpoint: 'https://northfield.sharepoint.com/_api/mcp',
    auth: 'oauth_client_credentials',
    timeoutMs: 8000,
    egressHosts: ['northfield.sharepoint.com'],
    dataClassification: 'internal',
    catalogId: 'cat_sharepoint',
    rotate: { production: 120 },
    reviewer: SECURITY,
    findings: ['Site list limited to Policies and Procedures'],
    operations: [
      { name: 'search_sites', tool: { description: 'Search policy pages and files', access: 'read', calls24h: 0, errorRate: 0, p95Ms: 0 }, input: [f('query', 'string', true)], binding: null, rate: 120, stub: { results: [{ title: 'Hardship program procedure', url: 'https://northfield.sharepoint.com/sites/policies/hardship' }] } },
      { name: 'get_file', tool: { description: 'Read a policy file', access: 'read', calls24h: 0, errorRate: 0, p95Ms: 0 }, input: [f('fileId', 'string', true)], binding: null, rate: 120, stub: { title: 'Hardship program procedure', version: '7.2' } },
    ],
    versions: [{ version: '1.0.3', daysAgo: 70, by: 'Tom Haddad', note: 'Retry on throttling', changes: [ch('search_sites', 'settings', 'Retries 429 responses twice')], pinnedBy: ['wf_advisor'] }],
    approvals: [{ workflowId: 'wf_advisor', operations: ['search_sites', 'get_file'], environment: 'test', expiresIn: -6, decidedBy: 'Tom Haddad', justification: 'Pilot: cite investment policy in portfolio notes' }],
  },
  {
    id: 'mod_payments_hub',
    name: 'payments-hub',
    displayName: 'Payments hub',
    system: 'Payments Hub',
    description: 'Wire history and holds on outbound wires.',
    type: 'http',
    ownerTeam: 'Payments Operations',
    ownerContacts: ['Maya Okafor'],
    endpoint: 'https://payments.northfield.internal/api',
    auth: 'api_key',
    authHeader: 'X-Api-Key',
    timeoutMs: 5000,
    egressHosts: ['payments.northfield.internal'],
    dataClassification: 'restricted',
    rotate: { production: 23 },
    reviewer: SECURITY,
    findings: ['Holds limited to 72 hours', 'Release needs a person'],
    operations: [
      { name: 'get_wire_history', method: 'GET', path: '/accounts/{accountId}/wires?days={days}', input: [f('accountId', 'string', true), f('days', 'integer', false, 'Look-back window, 1–30')], binding: bind('accountId', 'case.account'), masked: ['lastPayee.name'], rate: 300, stub: { attempts: 3, mfa: 'passed', lastPayee: { name: '[redacted]', ageHours: 6 } } },
      { name: 'place_wire_hold', method: 'POST', path: '/wires/{wireId}/hold', input: [f('wireId', 'string', true), f('action', 'string', true, undefined, { enum: ['hold', 'release'] }), f('hours', 'integer', true, 'Up to 72')], binding: null, rate: 60, amountMax: 250_000, stub: { held: true, releaseAt: '2026-10-05T14:00:00Z', callbackRequired: true } },
    ],
    versions: [
      { version: '1.5.0', daysAgo: 160, by: 'Maya Okafor', note: 'Hold release', changes: [ch('place_wire_hold', 'access_widened', 'Adds the release action', true)] },
      { version: '1.6.2', daysAgo: 12, by: 'Maya Okafor', note: 'Look-back window', changes: [ch('get_wire_history', 'schema_changed', 'Adds optional days')], pinnedBy: ['wf_wire'] },
    ],
    approvals: [{ workflowId: 'wf_wire', operations: ['get_wire_history', 'place_wire_hold'], expiresIn: 6, decidedBy: 'Maya Okafor', justification: 'Hold risky new-payee wires for an analyst', constraints: 'Holds up to 72 hours' }],
  },
  {
    id: 'mod_compliance_mcp',
    name: 'compliance-screening',
    displayName: 'Compliance screening',
    system: 'Compliance MCP',
    description: 'Watchlist screening and corporate registry lookups, served by Financial Crime’s MCP server.',
    type: 'mcp',
    ownerTeam: 'Financial Crime Ops',
    ownerContacts: ['Priya Shah'],
    endpoint: 'https://fincrime-mcp.northfield.internal/mcp',
    auth: 'mtls',
    timeoutMs: 10000,
    egressHosts: ['fincrime-mcp.northfield.internal'],
    dataClassification: 'confidential',
    rotate: { production: 75 },
    reviewer: SECURITY,
    findings: ['Results never include case notes from other investigations'],
    operations: [
      { name: 'screen_watchlists', input: [f('name', 'string', true), f('country', 'string', true), f('dateOfBirth', 'string', false, undefined, { format: 'date' })], binding: null, rate: 120, stub: { hits: [{ list: 'PEP domestic', score: 0.41 }], cleared: true } },
      { name: 'corporate_registry', input: [f('registryNumber', 'string', true), f('jurisdiction', 'string', false)], binding: null, rate: 60, stub: { name: 'Aurelia Holdings Ltd.', owners: 3, status: 'active' } },
    ],
    versions: [{ version: '2.1.0', daysAgo: 58, by: 'Priya Shah', note: 'Jurisdiction filter', changes: [ch('corporate_registry', 'schema_changed', 'Adds optional jurisdiction')], pinnedBy: ['wf_kyb', 'wf_mortgage'] }],
    approvals: [
      { workflowId: 'wf_kyb', operations: ['screen_watchlists', 'corporate_registry'], expiresIn: 13, decidedBy: 'Priya Shah', justification: 'Verify business owners before account opening' },
      { workflowId: 'wf_mortgage', operations: ['corporate_registry'], expiresIn: 160, decidedBy: 'Priya Shah', justification: 'Self-employed applicants’ businesses' },
    ],
  },
  {
    id: 'mod_work_number',
    name: 'work-number',
    displayName: 'The Work Number',
    system: 'The Work Number',
    description: 'Employment and income verification from Equifax Workforce Solutions.',
    type: 'http',
    ownerTeam: 'Lending Ops',
    ownerContacts: ['Maya Okafor'],
    endpoint: 'https://api.theworknumber.com/v2',
    auth: 'oauth_client_credentials',
    timeoutMs: 15000,
    egressHosts: ['api.theworknumber.com'],
    dataClassification: 'confidential',
    rotate: { production: 30 },
    reviewer: SECURITY,
    findings: ['Consent reference required on every call'],
    operations: [{ name: 'verify_employment', method: 'POST', path: '/verifications', input: [f('applicantId', 'string', true), f('employer', 'string', true), f('consentRef', 'string', true)], binding: null, masked: ['salary.base'], rate: 30, stub: { employed: true, since: '2019-03-01', salary: { base: '[redacted]' } } }],
    versions: [{ version: '2.0.1', daysAgo: 90, by: 'Maya Okafor', note: 'Timeout 15 s', changes: [ch('verify_employment', 'settings', 'Timeout 10 s → 15 s')], pinnedBy: ['wf_mortgage'] }],
    approvals: [{ workflowId: 'wf_mortgage', operations: ['verify_employment'], expiresIn: 200, decidedBy: 'Maya Okafor', justification: 'Income verification for pre-approval' }],
  },
  {
    id: 'mod_equifax',
    name: 'equifax-credit',
    displayName: 'Equifax credit',
    system: 'Equifax',
    description: 'Bureau reports and scores for consenting applicants.',
    type: 'http',
    ownerTeam: 'Lending Ops',
    ownerContacts: ['Maya Okafor'],
    endpoint: 'https://api.equifax.ca/credit/v1',
    auth: 'oauth_client_credentials',
    timeoutMs: 15000,
    egressHosts: ['api.equifax.ca'],
    dataClassification: 'restricted',
    rotate: { production: 61 },
    reviewer: SECURITY,
    findings: ['Soft pulls only; hard pulls stay with the underwriter'],
    operations: [{ name: 'run_credit_check', method: 'POST', path: '/reports', input: [f('applicantId', 'string', true), f('consentRef', 'string', true)], binding: null, masked: ['report.sin'], rate: 30, stub: { score: 742, tradelines: 9, inquiries90d: 1, report: { sin: '[redacted]' } } }],
    versions: [{ version: '1.4.0', daysAgo: 75, by: 'Maya Okafor', note: 'Consent reference', changes: [ch('run_credit_check', 'schema_changed', 'consentRef required')], pinnedBy: ['wf_mortgage'] }],
    approvals: [{ workflowId: 'wf_mortgage', operations: ['run_credit_check'], expiresIn: 200, decidedBy: 'Maya Okafor', justification: 'Credit check at pre-approval' }],
  },
  {
    id: 'mod_loan_origination',
    name: 'loan-origination',
    displayName: 'Loan origination',
    system: 'Loan Origination',
    description: 'Creates pre-approvals in the origination system.',
    type: 'openapi',
    ownerTeam: 'Lending Ops',
    ownerContacts: ['Maya Okafor'],
    endpoint: 'https://los.northfield.internal/api/v4',
    auth: 'oauth_client_credentials',
    timeoutMs: 8000,
    egressHosts: ['los.northfield.internal'],
    dataClassification: 'confidential',
    rotate: { production: 140 },
    reviewer: SECURITY,
    findings: ['Pre-approvals above $1M need an underwriter'],
    operations: [{ name: 'issue_preapproval', method: 'POST', path: '/applications/{applicationId}/preapprovals', input: [f('applicationId', 'string', true), f('amount', 'number', true, 'CAD'), f('rate', 'number', true, '%')], binding: null, rate: 30, stub: { preapprovalId: 'PA-60231', amount: 612000, rate: 5.24, expires: '2027-01-02' } }],
    versions: [{ version: '4.2.0', daysAgo: 64, by: 'Maya Okafor', note: 'Rate hold', changes: [ch('issue_preapproval', 'settings', '120-day rate hold')], pinnedBy: ['wf_mortgage'] }],
    approvals: [{ workflowId: 'wf_mortgage', operations: ['issue_preapproval'], expiresIn: 175, decidedBy: 'Maya Okafor', justification: 'Issue pre-approvals after underwriter sign-off' }],
  },
  {
    id: 'mod_branch_scheduler',
    name: 'branch-scheduler',
    displayName: 'Branch scheduler',
    system: 'Branch Scheduler',
    description: 'Branch and advisor appointment slots.',
    type: 'http',
    ownerTeam: 'Branch Network',
    ownerContacts: ['Tom Haddad'],
    endpoint: 'https://scheduler.northfield.internal/api',
    auth: 'api_key',
    authHeader: 'Authorization',
    timeoutMs: 5000,
    egressHosts: ['scheduler.northfield.internal'],
    dataClassification: 'internal',
    rotate: { production: 17 },
    reviewer: SECURITY,
    findings: ['Bookings are reversible by the customer; no approval needed'],
    operations: [{ name: 'book_appointment', method: 'POST', path: '/branches/{branch}/bookings', input: [f('branch', 'string', true), f('slot', 'string', true, undefined, { format: 'date-time' }), f('topic', 'string', false)], binding: null, rate: 60, requiresApproval: false, stub: { bookingId: 'BK-22019', branch: 'King & Bay', slot: '2026-10-06T10:30' } }],
    versions: [{ version: '1.1.0', daysAgo: 120, by: 'Tom Haddad', note: 'Topic field', changes: [ch('book_appointment', 'schema_changed', 'Adds optional topic')], pinnedBy: ['wf_branch_chat'] }],
    approvals: [{ workflowId: 'wf_branch_chat', operations: ['book_appointment'], expiresIn: 300, decidedBy: 'Tom Haddad', justification: 'Book appointments from chat' }],
  },
  {
    id: 'mod_knowledge',
    name: 'knowledge-search',
    displayName: 'Knowledge search',
    system: 'Data Hub',
    description: 'Searches the knowledge bases in Data Hub with citations. Served by the platform.',
    type: 'mcp',
    ownerTeam: 'Platform',
    ownerContacts: ['James Richardson'],
    endpoint: 'https://data-gateway.northfield.internal/knowledge/mcp',
    auth: 'none',
    timeoutMs: 4000,
    egressHosts: [],
    dataClassification: 'internal',
    reviewer: SECURITY,
    findings: ['Results filtered by the caller’s knowledge base grants'],
    operations: [{ name: 'search_knowledge', input: [f('query', 'string', true), f('collections', 'array', false)], binding: null, rate: 600, stub: { results: [{ title: 'Wire Fraud Playbook §4.2', score: 0.82 }] } }],
    versions: [{ version: '1.3.0', daysAgo: 30, by: 'James Richardson', note: 'Collection filter', changes: [ch('search_knowledge', 'schema_changed', 'Adds optional collections')], pinnedBy: ['wf_wire', 'wf_mortgage', 'wf_dispute', 'wf_kyb', 'wf_branch_chat'] }],
    approvals: ['wf_wire', 'wf_mortgage', 'wf_dispute', 'wf_kyb', 'wf_branch_chat'].map((w) => ({ workflowId: w, operations: ['search_knowledge'], expiresIn: 365, decidedBy: 'James Richardson', justification: 'Cite bank knowledge' })),
  },
];

/** Sample case contexts per workflow for the test console; bound fields are what a platform step resolved. */
export const RUN_CONTEXTS: Record<string, { caseId: string; label: string; bindings: Partial<Record<BindingSource, string>> }[]> = {
  wf_lending_inbox: [
    { caseId: 'CASE-4112', label: 'Hardship request · Marcus Webb', bindings: { 'case.id': 'CASE-4112', 'case.account': 'LN-0048213', 'case.customerId': 'CUS-118842', 'case.requesterEmail': 'marcus.webb@example.com', 'case.queue': 'Lending servicing' } },
    { caseId: 'CASE-4127', label: 'Unverified sender · account not resolved', bindings: { 'case.id': 'CASE-4127', 'case.queue': 'Lending servicing' } },
  ],
  wf_card_inbox: [{ caseId: 'CASE-4103', label: 'Fee complaint · Grace Kim', bindings: { 'case.id': 'CASE-4103', 'case.account': '4519-••••-2231', 'case.customerId': 'CUS-220917', 'case.requesterEmail': 'grace.kim@example.com', 'case.queue': 'Card services' } }],
  wf_dispute: [{ caseId: 'CASE-D-7781', label: 'Duplicate charge · Sarah Chen', bindings: { 'case.id': 'CASE-D-7781', 'case.account': '4519-••••-8840', 'case.customerId': 'CUS-301455' } }],
  wf_wire: [{ caseId: 'CASE-W-88213', label: 'New-payee wire · Hartwell Dental Corp', bindings: { 'case.id': 'CASE-W-88213', 'case.account': '8821-004417', 'case.customerId': 'CUS-004417' } }],
  wf_mortgage: [{ caseId: 'CASE-M-40912', label: 'Application APP-40912 · Priya Natarajan', bindings: { 'case.id': 'CASE-M-40912', 'case.customerId': 'CUS-409120' } }],
  wf_kyb: [{ caseId: 'CASE-K-1293', label: 'Aurelia Holdings onboarding', bindings: { 'case.id': 'CASE-K-1293', 'case.customerId': 'CUS-129388' } }],
  wf_branch_chat: [{ caseId: 'CASE-C-5521', label: 'Chat · anonymous visitor', bindings: { 'case.id': 'CASE-C-5521' } }],
  wf_advisor: [{ caseId: 'CASE-A-0091', label: 'Q3 review · Lin & Moreau LLP', bindings: { 'case.id': 'CASE-A-0091', 'case.customerId': 'CUS-700912' } }],
};

export const CATALOG: Omit<CatalogItem, 'moduleId'>[] = [
  { id: 'cat_core_banking', name: 'Core banking', system: 'Core Banking', category: 'Core systems', type: 'openapi', description: 'Accounts, loans, customer profiles and servicing actions.', operations: 6, auth: 'oauth_client_credentials', owner: 'Core Banking Platform', available: true },
  { id: 'cat_salesforce', name: 'Salesforce', system: 'Salesforce', category: 'CRM', type: 'mcp', description: 'Contacts, cases and activity through Salesforce’s hosted MCP server.', operations: 3, auth: 'oauth_client_credentials', owner: 'CRM Platform', available: true },
  { id: 'cat_m365_mail', name: 'Microsoft 365 mail', system: 'Outbound mail', category: 'Productivity', type: 'openapi', description: 'Read threads and reply from shared mailboxes.', operations: 2, auth: 'oauth_client_credentials', owner: 'Messaging Platform', available: true },
  { id: 'cat_sharepoint', name: 'SharePoint', system: 'SharePoint', category: 'Productivity', type: 'mcp', description: 'Search and read policy sites and files.', operations: 2, auth: 'oauth_client_credentials', owner: 'Digital Workplace', available: true },
  { id: 'cat_case_mgmt', name: 'Case management system', system: 'Case management system', category: 'Internal', type: 'mcp', description: 'Signed agreements, statements and identity documents.', operations: 2, auth: 'mtls', owner: 'Enterprise Data', available: true },
  { id: 'cat_servicenow', name: 'ServiceNow', system: 'ServiceNow', category: 'Internal', type: 'mcp', description: 'Incidents and requests in the IT and operations service desk.', operations: 5, auth: 'oauth_client_credentials', owner: 'IT Service Management', available: true },
  { id: 'cat_docusign', name: 'DocuSign', system: 'DocuSign', category: 'Productivity', type: 'openapi', description: 'Send envelopes and check signature status.', operations: 4, auth: 'oauth_client_credentials', owner: 'Digital Workplace', available: true },
  { id: 'cat_moodys', name: 'Moody’s KYC', system: 'Moody’s KYC', category: 'Risk & compliance', type: 'openapi', description: 'Entity verification and adverse media.', operations: 3, auth: 'api_key', owner: 'Financial Crime Ops', available: true },
  { id: 'cat_temenos_payments', name: 'Payments hub', system: 'Payments Hub', category: 'Core systems', type: 'http', description: 'Wire history and holds.', operations: 2, auth: 'api_key', owner: 'Payments Operations', available: true },
  { id: 'cat_bloomberg', name: 'Bloomberg data', system: 'Bloomberg', category: 'Risk & compliance', type: 'openapi', description: 'Market data for portfolio reviews. Licence review with Procurement.', operations: 0, auth: 'api_key', owner: 'Wealth', available: false },
];

const op = (name: string, description: string, access: ToolAccess, group: string, input: SchemaField[], method?: HttpMethod, path?: string): DiscoveredOperation => ({ name, description, access, group, input, method, path });

/** What discovery returns for catalog items and the generic MCP or OpenAPI sources. */
export const DISCOVERY: Record<string, { version: string; operations: DiscoveredOperation[]; warnings?: string[] }> = {
  cat_servicenow: {
    version: '1.0.0',
    operations: [
      op('get_incident', 'Read an incident', 'read', 'incidents', [f('number', 'string', true)]),
      op('list_incidents', 'Incidents for a caller', 'read', 'incidents', [f('callerId', 'string', true), f('state', 'string', false)]),
      op('create_incident', 'Open an incident', 'write', 'incidents', [f('shortDescription', 'string', true), f('callerId', 'string', true)]),
      op('add_work_note', 'Add a work note to an incident', 'write', 'incidents', [f('number', 'string', true), f('note', 'string', true)]),
      op('get_request', 'Read a catalog request', 'read', 'requests', [f('number', 'string', true)]),
    ],
  },
  cat_docusign: {
    version: '2.1.0',
    operations: [
      op('get_envelope_status', 'Status of an envelope', 'read', 'envelopes', [f('envelopeId', 'string', true)], 'GET', '/envelopes/{envelopeId}'),
      op('list_envelopes', 'Envelopes for a customer', 'read', 'envelopes', [f('customerEmail', 'string', true)], 'GET', '/envelopes'),
      op('send_envelope', 'Send a template for signature', 'write', 'envelopes', [f('templateId', 'string', true), f('signerEmail', 'string', true)], 'POST', '/envelopes'),
      op('void_envelope', 'Void a sent envelope', 'write', 'envelopes', [f('envelopeId', 'string', true), f('reason', 'string', true)], 'PUT', '/envelopes/{envelopeId}'),
    ],
  },
  cat_moodys: {
    version: '3.0.0',
    operations: [
      op('verify_entity', 'Match a business against registries', 'read', 'entities', [f('name', 'string', true), f('country', 'string', true)], 'POST', '/entities/verify'),
      op('adverse_media', 'Adverse media for a person or business', 'read', 'screening', [f('name', 'string', true)], 'POST', '/screening/media'),
      op('ownership_tree', 'Beneficial owners above a threshold', 'read', 'entities', [f('entityId', 'string', true), f('thresholdPct', 'number', false)], 'GET', '/entities/{entityId}/owners'),
    ],
  },
  mcp: {
    version: '1.0.0',
    operations: [
      op('list_records', 'List records', 'read', 'records', [f('query', 'string', false)]),
      op('get_record', 'Read one record', 'read', 'records', [f('id', 'string', true)]),
      op('create_record', 'Create a record', 'write', 'records', [f('fields', 'object', true)]),
      op('update_record', 'Update a record', 'write', 'records', [f('id', 'string', true), f('fields', 'object', true)]),
      op('delete_record', 'Delete a record', 'write', 'records', [f('id', 'string', true)]),
    ],
    warnings: ['delete_record removes data. It is left unselected; expose it only if a workflow needs it.'],
  },
  openapi: {
    version: '1.0.0',
    operations: [
      op('get_account', 'Read an account', 'read', 'accounts', [f('accountId', 'string', true)], 'GET', '/accounts/{accountId}'),
      op('list_accounts', 'Accounts for a customer', 'read', 'accounts', [f('customerId', 'string', true)], 'GET', '/customers/{customerId}/accounts'),
      op('update_account_alerts', 'Change alert preferences', 'write', 'accounts', [f('accountId', 'string', true), f('alerts', 'object', true)], 'PATCH', '/accounts/{accountId}/alerts'),
      op('create_payment', 'Create a payment', 'money_movement', 'payments', [f('fromAccount', 'string', true), f('payee', 'string', true), f('amount', 'number', true)], 'POST', '/payments'),
    ],
    warnings: ['create_payment moves money: every call needs a person’s approval and a four-eyes check.'],
  },
};

/** A credential reference path in the bank vault. */
export const vaultRef = (env: Environment, module: string, kind: CredentialKind) => `vault://${env === 'production' ? 'prod' : env}/data-gateway/${module}/${kind.replace(/_/g, '-')}`;
