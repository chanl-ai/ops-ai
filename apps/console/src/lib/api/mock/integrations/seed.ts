import type { AuthMethod, CatalogSystem, ScopeDef } from '@/lib/types/integrations';

const DAY = 86_400_000;
export const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();
export const inDays = (d: number) => new Date(Date.now() + d * DAY).toISOString();

const sc = (id: string, label: string, group: string, access: ScopeDef['access'], description: string): ScopeDef => ({ id, label, group, access, description });

export type CatalogSeed = Omit<CatalogSystem, 'connected' | 'connectionId'>;

/** Systems the bank lets teams connect, with the scopes each offers. */
export const CATALOG: CatalogSeed[] = [
  {
    id: 'cat_m365',
    name: 'Microsoft 365',
    kind: 'm365',
    category: 'Productivity',
    description: 'Shared mailboxes for case intake and replies, through Microsoft Graph.',
    authMethods: ['oauth_consent', 'service_principal'],
    instanceHint: 'northfield.onmicrosoft.com',
    owner: 'Messaging Platform',
    available: true,
    scopes: [
      sc('Mail.Read', 'Read mail', 'Mail', 'read', 'Reads messages and attachments in the mailboxes you name. Nothing outside them.'),
      sc('Mail.Send', 'Send mail', 'Mail', 'write', 'Sends replies as the mailbox. Replies still wait in Reviews when the deployment says so.'),
      sc('MailboxSettings.Read', 'Read mailbox settings', 'Mail', 'read', 'Reads folder names and automatic replies, to pick folders to watch.'),
      sc('Calendars.Read', 'Read calendars', 'Calendar', 'read', 'Reads free and busy times of the mailboxes, for booking callbacks.'),
    ],
  },
  {
    id: 'cat_sharepoint',
    name: 'SharePoint',
    kind: 'sharepoint',
    category: 'Knowledge',
    description: 'Policy sites, libraries and files for knowledge sources and lookups.',
    authMethods: ['service_principal', 'oauth_consent'],
    instanceHint: 'northfield.sharepoint.com',
    owner: 'Digital Workplace',
    available: true,
    scopes: [
      sc('Sites.Selected', 'Selected sites', 'Sites', 'read', 'Limits every other scope to the sites an admin grants this connection.'),
      sc('Sites.Read', 'Read sites and files', 'Files', 'read', 'Reads pages, lists and files in the granted sites, with their permissions.'),
      sc('Files.ReadWrite', 'Edit files', 'Files', 'write', 'Creates and edits files in the granted sites. Knowledge sources never need it.'),
    ],
  },
  {
    id: 'cat_confluence',
    name: 'Confluence',
    kind: 'confluence',
    category: 'Knowledge',
    description: 'Spaces, pages and attachments for knowledge sources.',
    authMethods: ['oauth_consent', 'api_key'],
    instanceHint: 'northfield.atlassian.net',
    owner: 'Digital Workplace',
    available: true,
    scopes: [
      sc('read:confluence-space', 'Read spaces', 'Content', 'read', 'Lists the spaces this connection can see, to pick which to index.'),
      sc('read:confluence-content', 'Read pages', 'Content', 'read', 'Reads page bodies and their page-level restrictions.'),
      sc('read:confluence-attachments', 'Read attachments', 'Content', 'read', 'Downloads files attached to pages.'),
      sc('write:confluence-content', 'Edit pages', 'Content', 'write', 'Creates and edits pages. No source or tool here uses it.'),
    ],
  },
  {
    id: 'cat_gdrive',
    name: 'Google Drive',
    kind: 'gdrive',
    category: 'Knowledge',
    description: 'Shared drives and folders; Docs, Sheets and Slides are exported.',
    authMethods: ['oauth_consent', 'service_principal'],
    instanceHint: 'northfieldbank.com',
    owner: 'Digital Workplace',
    available: true,
    scopes: [
      sc('drive.readonly', 'Read files', 'Files', 'read', 'Reads files and folders the connection is shared on.'),
      sc('drive.metadata.readonly', 'Read file details', 'Files', 'read', 'Reads names, owners and change history, to sync only what changed.'),
      sc('drive.file', 'Create files', 'Files', 'write', 'Creates files and edits the ones it created.'),
    ],
  },
  {
    id: 'cat_github',
    name: 'GitHub',
    kind: 'github',
    category: 'Knowledge',
    description: 'Repositories of documentation, read through a GitHub app installation.',
    authMethods: ['service_principal'],
    instanceHint: 'github.com/northfield-bank',
    owner: 'Platform',
    available: true,
    scopes: [
      sc('metadata:read', 'Read repository details', 'Repositories', 'read', 'Lists repositories and branches the app is installed on.'),
      sc('contents:read', 'Read contents', 'Repositories', 'read', 'Reads files and commits in those repositories.'),
    ],
  },
  {
    id: 'cat_notion',
    name: 'Notion',
    kind: 'notion',
    category: 'Knowledge',
    description: 'Pages and databases shared with the integration.',
    authMethods: ['oauth_consent'],
    instanceHint: 'notion.so/northfield',
    owner: 'Retail Product',
    available: true,
    scopes: [
      sc('read_content', 'Read pages', 'Content', 'read', 'Reads pages and databases someone shared with the integration.'),
      sc('read_comments', 'Read comments', 'Content', 'read', 'Reads comments on those pages.'),
    ],
  },
  {
    id: 'cat_zendesk',
    name: 'Zendesk',
    kind: 'zendesk',
    category: 'Knowledge',
    description: 'Help centre articles, and tickets for case history.',
    authMethods: ['oauth_consent', 'api_key'],
    instanceHint: 'northfield.zendesk.com',
    owner: 'Customer Care',
    available: true,
    scopes: [
      sc('hc:read', 'Read help centre', 'Help centre', 'read', 'Reads published articles, sections and categories.'),
      sc('tickets:read', 'Read tickets', 'Tickets', 'read', 'Reads tickets and their comments, which hold customer data.'),
      sc('tickets:write', 'Update tickets', 'Tickets', 'write', 'Adds comments and changes ticket status.'),
    ],
  },
  {
    id: 'cat_salesforce',
    name: 'Salesforce',
    kind: 'salesforce',
    category: 'CRM',
    description: 'Contacts, cases and activity through Salesforce’s hosted MCP server.',
    authMethods: ['oauth_consent', 'service_principal'],
    instanceHint: 'northfield.my.salesforce.com',
    owner: 'CRM Platform',
    available: true,
    scopes: [
      sc('contacts.read', 'Read contacts', 'Records', 'read', 'Finds contacts by email or phone and reads their details.'),
      sc('cases.read', 'Read cases', 'Records', 'read', 'Reads CRM cases and their activity.'),
      sc('cases.write', 'Update cases', 'Records', 'write', 'Logs activity and changes case fields.'),
      sc('knowledge.read', 'Read knowledge articles', 'Knowledge', 'read', 'Reads published Salesforce Knowledge articles.'),
    ],
  },
  {
    id: 'cat_core_banking',
    name: 'Core banking',
    kind: 'core_banking',
    category: 'Core systems',
    description: 'Accounts, loans, customer profiles and servicing actions in the core ledger.',
    authMethods: ['service_principal', 'mtls'],
    instanceHint: 'corebanking.api.northfield.internal',
    owner: 'Core Banking Platform',
    available: true,
    scopes: [
      sc('accounts.read', 'Read accounts', 'Accounts', 'read', 'Reads balances, rates and payment schedules of deposit and loan accounts.'),
      sc('customers.read', 'Read customer profiles', 'Customers', 'read', 'Reads names, contact details and products held. SIN and date of birth stay masked.'),
      sc('servicing.write', 'Servicing changes', 'Accounts', 'write', 'Changes addresses, payment dates and alert settings.'),
      sc('transfers.write', 'Internal transfers', 'Money movement', 'write', 'Moves money between a customer’s own accounts. Every call still needs a person’s approval.'),
    ],
  },
  {
    id: 'cat_card_platform',
    name: 'Card platform',
    kind: 'internal_api',
    category: 'Core systems',
    description: 'Card accounts, transactions and dispute actions.',
    authMethods: ['mtls'],
    instanceHint: 'cards.api.northfield.internal',
    owner: 'Card Services',
    available: true,
    scopes: [
      sc('cards.read', 'Read card accounts', 'Cards', 'read', 'Reads card status, limits and statements.'),
      sc('transactions.read', 'Read transactions', 'Cards', 'read', 'Reads posted and pending transactions.'),
      sc('disputes.write', 'Dispute actions', 'Disputes', 'write', 'Opens disputes and issues provisional credit.'),
    ],
  },
  {
    id: 'cat_case_mgmt',
    name: 'Case management system',
    kind: 'case_management',
    category: 'Internal',
    description: 'Signed agreements, statements and identity documents held on customer cases.',
    authMethods: ['mtls'],
    instanceHint: 'cms.northfield.internal',
    owner: 'Enterprise Data',
    available: true,
    scopes: [
      sc('documents.read', 'Read documents', 'Documents', 'read', 'Searches and reads documents on a customer’s cases.'),
      sc('cases.read', 'Read cases', 'Cases', 'read', 'Reads case status and history.'),
    ],
  },
  {
    id: 'cat_aws_s3',
    name: 'Amazon S3',
    kind: 'aws_s3',
    category: 'Internal',
    description: 'Object storage for every file the platform keeps: uploads, mail attachments, exports and sealed evidence.',
    authMethods: ['service_principal'],
    instanceHint: 's3.ca-central-1.amazonaws.com',
    owner: 'Cloud Platform',
    available: true,
    scopes: [
      sc('s3:PutObject', 'Write objects', 'Objects', 'write', 'Issues presigned PUT links for uploads and writes exports and evidence.'),
      sc('s3:GetObject', 'Read objects', 'Objects', 'read', 'Issues presigned GET links for downloads and reads files for indexing.'),
      sc('s3:DeleteObject', 'Delete objects', 'Objects', 'write', 'Deletes files whose retention has ended. Object Lock still refuses evidence.'),
      sc('kms:GenerateDataKey', 'Encrypt with the bank key', 'Encryption', 'write', 'Encrypts every object with the bank’s KMS key.'),
    ],
  },
  {
    id: 'cat_azure_blob',
    name: 'Azure Blob Storage',
    kind: 'azure_blob',
    category: 'Internal',
    description: 'Object storage on Azure for every file the platform keeps, for banks that run on Azure.',
    authMethods: ['service_principal'],
    instanceHint: 'nfopsaidev.blob.core.windows.net',
    owner: 'Cloud Platform',
    available: true,
    scopes: [
      sc('Blob.Write', 'Write blobs', 'Blobs', 'write', 'Issues SAS links for uploads and writes exports and evidence.'),
      sc('Blob.Read', 'Read blobs', 'Blobs', 'read', 'Issues SAS links for downloads and reads files for indexing.'),
      sc('Blob.Delete', 'Delete blobs', 'Blobs', 'write', 'Deletes files whose retention has ended. Immutability policies still refuse evidence.'),
    ],
  },
  {
    id: 'cat_servicenow',
    name: 'ServiceNow',
    kind: 'servicenow',
    category: 'Internal',
    description: 'Incidents and requests in the IT and operations service desk.',
    authMethods: ['oauth_consent', 'service_principal'],
    instanceHint: 'northfield.service-now.com',
    owner: 'IT Service Management',
    available: true,
    scopes: [
      sc('incident.read', 'Read incidents', 'Incidents', 'read', 'Reads incidents and their work notes.'),
      sc('incident.write', 'Open and update incidents', 'Incidents', 'write', 'Opens incidents and adds work notes.'),
      sc('sc_request.read', 'Read catalog requests', 'Requests', 'read', 'Reads service catalog requests and their approvals.'),
    ],
  },
  {
    id: 'cat_payments_hub',
    name: 'Payments hub',
    kind: 'payments_hub',
    category: 'Core systems',
    description: 'Wire history, payee details and holds.',
    authMethods: ['api_key', 'mtls'],
    instanceHint: 'payments.api.northfield.internal',
    owner: 'Payments Operations',
    available: true,
    scopes: [
      sc('wires.read', 'Read wires', 'Wires', 'read', 'Reads wire history and payee details for an account.'),
      sc('holds.write', 'Place and release holds', 'Wires', 'write', 'Places or releases a hold on an outbound wire. Every call needs a person’s approval.'),
    ],
  },
  {
    id: 'cat_internal_mcp',
    name: 'Internal MCP server',
    kind: 'internal_mcp',
    category: 'Internal',
    description: 'Any MCP server inside the bank network. Its tool list becomes a tool module.',
    authMethods: ['service_principal', 'mtls', 'api_key'],
    instanceHint: 'https://<server>.northfield.internal/mcp',
    owner: 'Platform',
    available: true,
    scopes: [
      sc('tools.list', 'List tools', 'Tools', 'read', 'Reads the server’s tool list, to choose which to expose.'),
      sc('tools.call', 'Call tools', 'Tools', 'write', 'Calls the tools a module exposes, under each workflow’s approval.'),
    ],
  },
  {
    id: 'cat_compliance_mcp',
    name: 'Compliance MCP',
    kind: 'internal_mcp',
    category: 'Risk & compliance',
    description: 'Sanctions screening and corporate registry lookups.',
    authMethods: ['mtls', 'service_principal'],
    instanceHint: 'https://compliance-mcp.northfield.internal/mcp',
    owner: 'Financial Crime Ops',
    available: true,
    scopes: [
      sc('screening.read', 'Screen names', 'Screening', 'read', 'Checks names against sanctions and PEP lists.'),
      sc('registry.read', 'Read the corporate registry', 'Registry', 'read', 'Reads incorporation records and directors.'),
    ],
  },
  {
    id: 'cat_equifax',
    name: 'Equifax',
    kind: 'credit_bureau',
    category: 'Risk & compliance',
    description: 'Bureau reports and scores for consenting applicants.',
    authMethods: ['service_principal'],
    instanceHint: 'api.equifax.ca',
    owner: 'Lending Ops',
    available: true,
    scopes: [sc('reports.read', 'Pull credit reports', 'Reports', 'read', 'Pulls a report for an applicant with a consent reference. Each pull is billed.')],
  },
  {
    id: 'cat_work_number',
    name: 'The Work Number',
    kind: 'credit_bureau',
    category: 'Risk & compliance',
    description: 'Employment and income verification.',
    authMethods: ['service_principal'],
    instanceHint: 'api.theworknumber.com',
    owner: 'Lending Ops',
    available: true,
    scopes: [sc('verifications.read', 'Verify employment', 'Verifications', 'read', 'Confirms an applicant’s employer and income with their consent.')],
  },
  {
    id: 'cat_loan_origination',
    name: 'Loan origination',
    kind: 'core_banking',
    category: 'Core systems',
    description: 'Mortgage and loan applications, conditions and pre-approvals.',
    authMethods: ['service_principal'],
    instanceHint: 'los.api.northfield.internal',
    owner: 'Lending Ops',
    available: true,
    scopes: [
      sc('applications.read', 'Read applications', 'Applications', 'read', 'Reads applications, documents received and conditions.'),
      sc('applications.write', 'Update applications', 'Applications', 'write', 'Adds conditions and notes.'),
      sc('preapprovals.write', 'Issue pre-approvals', 'Applications', 'write', 'Issues a pre-approval letter. A person approves each one.'),
    ],
  },
  {
    id: 'cat_branch_scheduler',
    name: 'Branch scheduler',
    kind: 'internal_api',
    category: 'Internal',
    description: 'Advisor availability and appointment booking.',
    authMethods: ['api_key'],
    instanceHint: 'scheduler.api.northfield.internal',
    owner: 'Branch Network',
    available: true,
    scopes: [
      sc('slots.read', 'Read availability', 'Appointments', 'read', 'Reads open appointment slots by branch and advisor.'),
      sc('appointments.write', 'Book appointments', 'Appointments', 'write', 'Books and cancels appointments.'),
    ],
  },
  {
    id: 'cat_docusign',
    name: 'DocuSign',
    kind: 'internal_api',
    category: 'Productivity',
    description: 'Send envelopes and check signature status.',
    authMethods: ['oauth_consent'],
    instanceHint: 'northfield.docusign.net',
    owner: 'Digital Workplace',
    available: true,
    scopes: [
      sc('signature.read', 'Read envelopes', 'Envelopes', 'read', 'Reads envelope status and signers.'),
      sc('signature.write', 'Send envelopes', 'Envelopes', 'write', 'Sends templates for signature and voids envelopes.'),
    ],
  },
  {
    id: 'cat_bloomberg',
    name: 'Bloomberg data',
    kind: 'internal_api',
    category: 'Risk & compliance',
    description: 'Market data for portfolio reviews.',
    authMethods: ['api_key'],
    instanceHint: 'api.bloomberg.com',
    owner: 'Wealth',
    available: false,
    unavailableReason: 'Licence review with Procurement',
    scopes: [],
  },
];

export interface ConnectionSeed {
  id: string;
  catalogId: string;
  name: string;
  instanceUrl: string;
  tenant?: string;
  authMethod: AuthMethod;
  scopes: string[];
  ownerTeam: string;
  createdBy: string;
  createdDaysAgo: number;
  /** Days until consent or the credential expires; negative when already expired. */
  expiresIn?: number;
  rotateIn?: number;
  base: 'healthy' | 'needs_reconnect' | 'revoked' | 'error';
  lastError?: string;
  /** Days since the status changed, for the health check history. */
  since?: number;
}

const vault = (path: string) => `vault://prod/integrations/${path}`;

/**
 * The connections every source, tool module and mailbox in the fixtures reads through. The lending mailbox's
 * consent has expired and the Wire fraud playbook's Confluence connection is revoked, so their dependants show it.
 */
export const CONNECTIONS: (ConnectionSeed & { credentialRef?: string })[] = [
  { id: 'int_sharepoint', catalogId: 'cat_sharepoint', name: 'SharePoint · policy sites', instanceUrl: 'https://northfield.sharepoint.com', tenant: 'northfield.onmicrosoft.com', authMethod: 'service_principal', scopes: ['Sites.Selected', 'Sites.Read'], ownerTeam: 'Platform', createdBy: 'James Richardson', createdDaysAgo: 190, expiresIn: 210, rotateIn: 40, base: 'healthy', credentialRef: vault('sharepoint/app-certificate') },
  { id: 'int_confluence', catalogId: 'cat_confluence', name: 'Confluence · northfield.atlassian.net', instanceUrl: 'https://northfield.atlassian.net', authMethod: 'oauth_consent', scopes: ['read:confluence-space', 'read:confluence-content', 'read:confluence-attachments'], ownerTeam: 'Fraud Strategy', createdBy: 'Maya Okafor', createdDaysAgo: 150, expiresIn: 35, base: 'revoked', since: 9, lastError: 'Atlassian returned 401: the app’s access was revoked. Syncs stop until it is reconnected.' },
  { id: 'int_github', catalogId: 'cat_github', name: 'GitHub app · northfield-bank', instanceUrl: 'https://github.com/northfield-bank', authMethod: 'service_principal', scopes: ['metadata:read', 'contents:read'], ownerTeam: 'Platform', createdBy: 'James Richardson', createdDaysAgo: 140, expiresIn: 300, rotateIn: 120, base: 'healthy', credentialRef: vault('github/app-private-key') },
  { id: 'int_notion', catalogId: 'cat_notion', name: 'Notion · Northfield Product', instanceUrl: 'https://notion.so/northfield', authMethod: 'oauth_consent', scopes: ['read_content'], ownerTeam: 'Retail Banking', createdBy: 'Tom Haddad', createdDaysAgo: 160, expiresIn: 18, base: 'healthy' },
  { id: 'int_zendesk', catalogId: 'cat_zendesk', name: 'Zendesk · help centre', instanceUrl: 'https://northfield.zendesk.com', authMethod: 'oauth_consent', scopes: ['hc:read'], ownerTeam: 'Retail Banking', createdBy: 'Tom Haddad', createdDaysAgo: 75, expiresIn: 120, base: 'healthy' },
  { id: 'int_m365_mail', catalogId: 'cat_m365', name: 'Microsoft 365 · outbound mail app', instanceUrl: 'https://graph.microsoft.com', tenant: 'northfield.onmicrosoft.com', authMethod: 'service_principal', scopes: ['Mail.Read', 'Mail.Send'], ownerTeam: 'Platform', createdBy: 'James Richardson', createdDaysAgo: 120, expiresIn: 245, rotateIn: 60, base: 'healthy', credentialRef: vault('m365/outbound-mail-app') },
  { id: 'int_m365_cards', catalogId: 'cat_m365', name: 'Microsoft 365 · cardservices@', instanceUrl: 'https://graph.microsoft.com', tenant: 'northfield.onmicrosoft.com', authMethod: 'oauth_consent', scopes: ['Mail.Read', 'Mail.Send', 'MailboxSettings.Read'], ownerTeam: 'Card Services', createdBy: 'Daniel Brooks', createdDaysAgo: 45, expiresIn: 64, base: 'healthy' },
  { id: 'int_m365_lending', catalogId: 'cat_m365', name: 'Microsoft 365 · lendingservicing@', instanceUrl: 'https://graph.microsoft.com', tenant: 'northfield.onmicrosoft.com', authMethod: 'oauth_consent', scopes: ['Mail.Read', 'Mail.Send'], ownerTeam: 'Lending Ops', createdBy: 'Tom Haddad', createdDaysAgo: 20, expiresIn: -1, base: 'needs_reconnect', since: 1, lastError: 'Microsoft Graph returned 401: the mailbox consent expired. New email is not being read.' },
  { id: 'int_core_banking', catalogId: 'cat_core_banking', name: 'Core banking', instanceUrl: 'https://corebanking.api.northfield.internal/v3', authMethod: 'service_principal', scopes: ['accounts.read', 'customers.read', 'servicing.write', 'transfers.write'], ownerTeam: 'Platform', createdBy: 'Daniel Brooks', createdDaysAgo: 230, expiresIn: 135, rotateIn: 41, base: 'healthy', credentialRef: vault('core-banking/oauth-client') },
  { id: 'int_card_platform', catalogId: 'cat_card_platform', name: 'Card platform', instanceUrl: 'https://cards.api.northfield.internal', authMethod: 'mtls', scopes: ['cards.read', 'transactions.read', 'disputes.write'], ownerTeam: 'Card Services', createdBy: 'Daniel Brooks', createdDaysAgo: 210, expiresIn: 160, rotateIn: 70, base: 'healthy', credentialRef: vault('card-platform/client-certificate') },
  { id: 'int_salesforce', catalogId: 'cat_salesforce', name: 'Salesforce', instanceUrl: 'https://northfield.my.salesforce.com', authMethod: 'oauth_consent', scopes: ['contacts.read', 'cases.read', 'cases.write'], ownerTeam: 'Retail Banking', createdBy: 'Lena Fischer', createdDaysAgo: 40, expiresIn: 12, base: 'healthy' },
  { id: 'int_case_mgmt', catalogId: 'cat_case_mgmt', name: 'Case management system', instanceUrl: 'https://cms.northfield.internal/mcp', authMethod: 'mtls', scopes: ['documents.read', 'cases.read'], ownerTeam: 'Platform', createdBy: 'James Richardson', createdDaysAgo: 30, expiresIn: 330, rotateIn: 150, base: 'healthy', credentialRef: vault('case-management/client-certificate') },
  { id: 'int_payments_hub', catalogId: 'cat_payments_hub', name: 'Payments hub', instanceUrl: 'https://payments.api.northfield.internal', authMethod: 'api_key', scopes: ['wires.read', 'holds.write'], ownerTeam: 'Fraud Strategy', createdBy: 'Maya Okafor', createdDaysAgo: 260, expiresIn: 9, rotateIn: 9, base: 'healthy', credentialRef: vault('payments-hub/api-key') },
  { id: 'int_compliance_mcp', catalogId: 'cat_compliance_mcp', name: 'Compliance MCP', instanceUrl: 'https://compliance-mcp.northfield.internal/mcp', authMethod: 'mtls', scopes: ['screening.read', 'registry.read'], ownerTeam: 'Fraud Strategy', createdBy: 'Maya Okafor', createdDaysAgo: 100, expiresIn: 200, rotateIn: 90, base: 'healthy', credentialRef: vault('compliance-mcp/client-certificate') },
  { id: 'int_work_number', catalogId: 'cat_work_number', name: 'The Work Number', instanceUrl: 'https://api.theworknumber.com', authMethod: 'service_principal', scopes: ['verifications.read'], ownerTeam: 'Lending Ops', createdBy: 'Priya Shah', createdDaysAgo: 85, expiresIn: 95, rotateIn: -2, base: 'error', since: 0.2, lastError: 'The token endpoint returned 400 invalid_client: the client secret was rotated in the vault and this reference points at the old version.', credentialRef: vault('work-number/oauth-client-2025') },
  { id: 'int_equifax', catalogId: 'cat_equifax', name: 'Equifax', instanceUrl: 'https://api.equifax.ca/business/consumer-credit/v1', authMethod: 'service_principal', scopes: ['reports.read'], ownerTeam: 'Lending Ops', createdBy: 'Priya Shah', createdDaysAgo: 110, expiresIn: 75, rotateIn: 75, base: 'healthy', credentialRef: vault('equifax/oauth-client') },
  { id: 'int_loan_origination', catalogId: 'cat_loan_origination', name: 'Loan origination', instanceUrl: 'https://los.api.northfield.internal', authMethod: 'service_principal', scopes: ['applications.read', 'applications.write', 'preapprovals.write'], ownerTeam: 'Lending Ops', createdBy: 'Priya Shah', createdDaysAgo: 120, expiresIn: 140, rotateIn: 55, base: 'healthy', credentialRef: vault('loan-origination/oauth-client') },
  { id: 'int_aws_storage', catalogId: 'cat_aws_s3', name: 'Amazon S3 · ops files', instanceUrl: 'https://s3.ca-central-1.amazonaws.com', authMethod: 'service_principal', scopes: ['s3:PutObject', 's3:GetObject', 's3:DeleteObject', 'kms:GenerateDataKey'], ownerTeam: 'Platform', createdBy: 'James Richardson', createdDaysAgo: 210, expiresIn: 330, rotateIn: 80, base: 'healthy', credentialRef: vault('aws/opsai-files-role') },
  { id: 'int_azure_storage', catalogId: 'cat_azure_blob', name: 'Azure Blob · dev files', instanceUrl: 'https://nfopsaidev.blob.core.windows.net', authMethod: 'service_principal', scopes: ['Blob.Write', 'Blob.Read', 'Blob.Delete'], ownerTeam: 'Platform', createdBy: 'James Richardson', createdDaysAgo: 60, expiresIn: 300, rotateIn: 120, base: 'healthy', credentialRef: vault('azure/opsai-dev-files-sp') },
  { id: 'int_branch_scheduler', catalogId: 'cat_branch_scheduler', name: 'Branch scheduler', instanceUrl: 'https://scheduler.api.northfield.internal', authMethod: 'api_key', scopes: ['slots.read', 'appointments.write'], ownerTeam: 'Retail Banking', createdBy: 'Tom Haddad', createdDaysAgo: 70, expiresIn: 280, rotateIn: 100, base: 'healthy', credentialRef: vault('branch-scheduler/api-key') },
];

/** Which connection each seeded tool module calls through. Data Hub knowledge is served inside the gateway. */
export const MODULE_CONNECTION: Record<string, string> = {
  mod_core_banking: 'int_core_banking',
  mod_card_platform: 'int_card_platform',
  mod_m365_mail: 'int_m365_mail',
  mod_salesforce: 'int_salesforce',
  mod_case_mgmt: 'int_case_mgmt',
  mod_sharepoint: 'int_sharepoint',
  mod_payments_hub: 'int_payments_hub',
  mod_compliance_mcp: 'int_compliance_mcp',
  mod_work_number: 'int_work_number',
  mod_equifax: 'int_equifax',
  mod_loan_origination: 'int_loan_origination',
  mod_branch_scheduler: 'int_branch_scheduler',
};

/** Which connection each seeded mailbox deployment reads through. */
export const MAILBOX_CONNECTION: Record<string, string> = {
  dp_card_mailbox: 'int_m365_cards',
  dp_lending_mailbox: 'int_m365_lending',
};
