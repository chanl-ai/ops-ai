import type { FilePurpose, FileReference, FileSensitivity, PurposeLimit, RetentionClass, StorageSettings } from '@/lib/types/files';

const DAY = 86_400_000;
export const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();

export const RETENTION_CLASSES: RetentionClass[] = [
  { id: 'rc_knowledge', name: 'Knowledge content', days: null, purposes: ['knowledge_source', 'tool_spec', 'avatar'], worm: false, keepUntilEnd: false },
  { id: 'rc_case', name: 'Case records · 7 years', days: 2555, purposes: ['case_attachment'], worm: false, keepUntilEnd: true },
  { id: 'rc_chat', name: 'Chat attachments · 1 year', days: 365, purposes: ['chat_attachment'], worm: false, keepUntilEnd: false },
  { id: 'rc_import', name: 'Test imports · 2 years', days: 730, purposes: ['test_import'], worm: false, keepUntilEnd: false },
  { id: 'rc_evidence', name: 'Model evidence · 10 years', days: 3650, purposes: ['evidence_bundle'], worm: true, keepUntilEnd: true },
  { id: 'rc_export', name: 'Exports · 30 days', days: 30, purposes: ['export'], worm: false, keepUntilEnd: false },
];

export const LIMITS: PurposeLimit[] = [
  { purpose: 'knowledge_source', allowedTypes: ['pdf', 'docx', 'xlsx', 'pptx', 'csv', 'txt', 'md', 'html'], maxSizeMb: 50 },
  { purpose: 'chat_attachment', allowedTypes: ['pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'csv', 'eml'], maxSizeMb: 10 },
  { purpose: 'case_attachment', allowedTypes: ['pdf', 'png', 'jpg', 'jpeg', 'docx', 'docm', 'xlsx', 'csv', 'eml', 'msg', 'zip'], maxSizeMb: 25 },
  { purpose: 'test_import', allowedTypes: ['csv'], maxSizeMb: 5 },
  { purpose: 'evidence_bundle', allowedTypes: ['zip'], maxSizeMb: 500 },
  { purpose: 'export', allowedTypes: ['csv', 'zip'], maxSizeMb: 200 },
  { purpose: 'tool_spec', allowedTypes: ['json', 'yaml', 'yml'], maxSizeMb: 2 },
  { purpose: 'avatar', allowedTypes: ['png', 'jpg', 'svg'], maxSizeMb: 1 },
];

export const STORAGE: Omit<StorageSettings, 'updatedAt'> & { updatedDaysAgo: number } = {
  version: 4,
  updatedBy: 'James Richardson',
  updatedDaysAgo: 12,
  targets: [
    { environment: 'prod', backend: 's3', connectionId: 'int_aws_storage', residency: 'Canada (Central), ca-central-1', s3: { bucket: 'northfield-opsai-prod-files', region: 'ca-central-1', kmsKeyAlias: 'alias/opsai-prod-files', objectLockEvidence: true } },
    { environment: 'test', backend: 's3', connectionId: 'int_aws_storage', residency: 'Canada (Central), ca-central-1', s3: { bucket: 'northfield-opsai-test-files', region: 'ca-central-1', kmsKeyAlias: 'alias/opsai-test-files', objectLockEvidence: true } },
    { environment: 'dev', backend: 'azure_blob', connectionId: 'int_azure_storage', residency: 'Canada Central', azure: { account: 'nfopsaidev', container: 'files', encryptionScope: 'opsai-dev-cmk', immutabilityPolicy: false } },
  ],
  limits: LIMITS,
  scanning: { enabled: true, engine: 'clamav' },
  retentionClasses: RETENTION_CLASSES,
  signedUrlMinutes: 5,
};

export const SUGGESTED: Record<FilePurpose, FileSensitivity> = {
  knowledge_source: 'internal',
  chat_attachment: 'confidential',
  case_attachment: 'confidential',
  test_import: 'internal',
  evidence_bundle: 'restricted',
  export: 'restricted',
  tool_spec: 'internal',
  avatar: 'public',
};

export interface FileSeed {
  id: string;
  name: string;
  purpose: FilePurpose;
  team: string;
  by: string;
  daysAgo: number;
  sizeKb: number;
  refs?: Omit<FileReference, 'addedAt'>[];
  sensitivity?: FileSensitivity;
  scan?: 'infected' | 'failed' | 'pending';
  scanDetail?: string;
  hold?: { by: string; reason: string; daysAgo: number };
  versions?: number;
  content?: string;
}

const source = (id: string, name: string): Omit<FileReference, 'addedAt'> => ({ type: 'source', id, name, href: `/sources/${id}` });

/** Uploaded files outside the case mailboxes (those come from the cases mock as intake attachments). */
export function fileSeeds(contracts: string[], lendingFiles: string[]): FileSeed[] {
  const lending = source('src_lending_policies', 'Lending policies and fee schedules');
  const disputes = source('src_contracts', 'Dispute rights guides');
  return [
    ...lendingFiles.map((name, i): FileSeed => ({ id: `file_lending_${i}`, name, purpose: 'knowledge_source', team: 'Lending Ops', by: 'Priya Shah', daysAgo: 40 + i * 6, sizeKb: 180 + i * 97, refs: [lending], versions: name.includes('v6') ? 3 : 1 })),
    { id: 'file_lending_9', name: 'Payment deferral policy v1.0.pdf', purpose: 'knowledge_source', team: 'Lending Ops', by: 'Priya Shah', daysAgo: 340, sizeKb: 410, refs: [lending] },
    { id: 'file_lending_10', name: 'Payment deferral policy v2.0.pdf', purpose: 'knowledge_source', team: 'Lending Ops', by: 'Priya Shah', daysAgo: 200, sizeKb: 436, refs: [lending], versions: 2 },
    ...contracts.map((name, i): FileSeed => ({ id: `file_dispute_guide_${i}`, name, purpose: 'knowledge_source', team: 'Card Services', by: 'Daniel Brooks', daysAgo: 30 + i * 9, sizeKb: 220 + i * 61, refs: [disputes], scan: i === 6 ? 'failed' : undefined, scanDetail: i === 6 ? 'The PDF is encrypted, so the scanner could not read it. Upload an unlocked copy.' : undefined })),
    { id: 'file_fee_macro', name: 'Fee schedule 2026 Q4 (macros).xlsm', purpose: 'knowledge_source', team: 'Retail Banking', by: 'Tom Haddad', daysAgo: 3, sizeKb: 88, scan: 'infected', scanDetail: 'Doc.Dropper.Agent-1234 (macro downloader)' },
    { id: 'file_rate_oct', name: 'Rate card — October 2026.xlsx', purpose: 'knowledge_source', team: 'Lending Ops', by: 'Priya Shah', daysAgo: 0.01, sizeKb: 64, scan: 'pending' },
    { id: 'file_hardship_evals', name: 'hardship-eval-cases.csv', purpose: 'test_import', team: 'Lending Ops', by: 'Priya Shah', daysAgo: 21, sizeKb: 14, refs: [{ type: 'eval_set', id: 'ag_loan', name: 'Mortgage Intake eval cases', href: '/agents/ag_loan?tab=evals' }], content: 'name,input,runAs,knowledgeBases,checks\nHardship request,"I lost my job, can I pause payments?",,Lending policy,reply_contains:hardship\nPayoff statement,Send me my payoff amount,,Lending policy,calls_tool:send_payoff_statement' },
    { id: 'file_dispute_tests', name: 'card-dispute-tests.csv', purpose: 'test_import', team: 'Card Services', by: 'Daniel Brooks', daysAgo: 48, sizeKb: 9, refs: [{ type: 'test_set', id: 'wf_dispute', name: 'Card dispute resolution tests', href: '/workflows/wf_dispute?tab=tests' }], content: 'name,input,pauses,callsTool,replyContains\nDuplicate charge,I was charged twice at LF Market,yes,issue_provisional_credit,\nLost card,My card is gone,no,place_card_block,blocked' },
    { id: 'file_old_tests', name: 'wire-tests-draft.csv', purpose: 'test_import', team: 'Fraud Strategy', by: 'Maya Okafor', daysAgo: 95, sizeKb: 6, content: 'name,input,pauses,callsTool,replyContains\nNew payee,Wire $60,000 to a payee added today,yes,place_wire_hold,' },
    { id: 'file_chat_statement', name: 'wire-confirmation-0912.pdf', purpose: 'chat_attachment', team: 'Fraud Strategy', by: 'Maya Okafor', daysAgo: 52, sizeKb: 132 },
    { id: 'file_chat_screenshot', name: 'app-error-screenshot.png', purpose: 'chat_attachment', team: 'Retail Banking', by: 'Tom Haddad', daysAgo: 6, sizeKb: 410 },
    { id: 'file_spec_payments', name: 'payments-hub-openapi.yaml', purpose: 'tool_spec', team: 'Fraud Strategy', by: 'Maya Okafor', daysAgo: 260, sizeKb: 46, refs: [{ type: 'tool_module', id: 'mod_payments_hub', name: 'Payments hub', href: '/tools/mod_payments_hub' }], versions: 2, content: 'openapi: 3.1.0\ninfo:\n  title: Payments hub\n  version: 2.3.0\npaths:\n  /wires/{id}/hold:\n    post:\n      operationId: place_wire_hold' },
    { id: 'file_logo', name: 'northfield-logo.svg', purpose: 'avatar', team: 'Platform', by: 'James Richardson', daysAgo: 300, sizeKb: 4, sensitivity: 'public' },
    { id: 'file_audit_sep', name: 'audit-log-2026-09-08.csv', purpose: 'export', team: 'Platform', by: 'James Richardson', daysAgo: 27, sizeKb: 2210, content: 'at,actor,action,target,summary\n2026-09-08T14:02:11Z,Priya Shah,published,workflow,Published Lending servicing inbox v3' },
    { id: 'file_evidence_wire_v6', name: 'evidence-outbound-wire-review-v6.zip', purpose: 'evidence_bundle', team: 'Fraud Strategy', by: 'Eval runner', daysAgo: 70, sizeKb: 3840, refs: [{ type: 'evidence', id: 'mr_wf_wire', name: 'Outbound wire review v6', href: '/model-risk/mr_wf_wire' }], hold: { by: 'Legal (Litigation)', reason: 'LH-2026-014: wire fraud claim, preserve every record for the v6 release', daysAgo: 30 } },
  ];
}

/** Text the mock preview and download show; real previews are rendered by the server after scanning. */
export const PDF_FIRST_PAGE: Record<string, string> = {
  'Hardship program guidelines.pdf': 'Hardship program guidelines\n\n1. Eligibility. A borrower qualifies after an involuntary loss of income of at least 30% …',
  'Lending policy v6 — personal loans.pdf': 'Lending policy v6: personal loans\n\nEffective 1 July 2026. Supersedes v5.\n\n§1 Scope. This policy applies to unsecured personal loans up to $50,000 …',
};
