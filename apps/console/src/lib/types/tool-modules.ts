import type { ToolAccess } from './domain';
import type { ToolCallRow } from './governance';

/**
 * Tool modules (spec 03 §4.1): one system connected once, holding the operations agents call. A module version is
 * security-reviewed once per major version (00 A1) and each workflow uses it only under an approval with expiry.
 */
export type ModuleType = 'mcp' | 'openapi' | 'http' | 'code';
export type ModuleStatus = 'draft' | 'in_review' | 'published' | 'revoked';
/** Computed by the API from the security review, workflow approvals and drift. */
export type ModuleApprovalState = 'draft' | 'approved' | 'needs_approval' | 'expiring' | 'expired';
/** `expiring` holds modules whose approvals expire within 30 days; already expired ones have their own view. */
export type ModuleView = 'all' | 'needs_approval' | 'expiring' | 'expired' | 'failing';
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type Environment = 'dev' | 'test' | 'production';

export interface ModuleRef {
  id: string;
  name: string;
}

export interface ToolModule {
  id: string;
  /** Stable kebab-case name workflows pin; never a row id. */
  name: string;
  displayName: string;
  system: string;
  description: string;
  type: ModuleType;
  status: ModuleStatus;
  /** Semver of the current published (or draft) version. */
  version: string;
  major: number;
  /** Team that owns the system and decides approvals. */
  ownerTeam: string;
  /** Base URL, MCP server URL or spec URL. */
  endpoint: string;
  operationCount: number;
  accessClasses: ToolAccess[];
  approvalState: ModuleApprovalState;
  /** Earliest expiry among active workflow approvals. */
  nextExpiry?: string;
  pendingApprovals: number;
  workflows: ModuleRef[];
  calls24h: number;
  errorRate: number;
  p95Ms: number;
  reachable: boolean;
  /** The MCP server's tool list no longer matches the reviewed snapshot. */
  drift: boolean;
  updatedAt: string;
}

export type ModuleFilters = { type?: string[]; access?: string[]; approvalState?: string[] };
export type ModuleViewCounts = Record<ModuleView, number>;

export interface ModuleStats {
  modules: number;
  operations: number;
  calls24h: number;
  /** Failed calls over all calls, last 24h. */
  errorRate: number;
  moneyOperations: number;
  /** Workflow approvals that expire within 30 days. */
  expiringApprovals: number;
  /** Modules whose approvals expire within 30 days; equals the Expiring soon view count. */
  expiringModules: number;
}

export type SchemaType = 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array';

export interface SchemaField {
  name: string;
  type: SchemaType;
  required: boolean;
  description?: string;
  format?: string;
  enum?: string[];
  example?: string;
}

/** Case fields a platform step binds; model output alone never binds one (spec 03 §4.3). */
export type BindingSource = 'case.account' | 'case.customerId' | 'case.id' | 'case.requesterEmail' | 'case.queue';

export interface SubjectBinding {
  /** Input field naming the record, e.g. `loanAccountId`. */
  arg: string;
  bindTo: BindingSource;
  /** `equals`: must equal the binding and is filled from it. `within`: may name a child record of it. */
  mode: 'equals' | 'within';
  /** Deny with `subject_unbound` when the run has no value for the binding. */
  required: boolean;
}

export interface ModuleOperation {
  id: string;
  /** The grantable tool record agents hold. */
  toolId: string;
  name: string;
  description: string;
  access: ToolAccess;
  /** Exposed through the gateway; hidden operations stay in the manifest but cannot be called. */
  enabled: boolean;
  method?: HttpMethod;
  path?: string;
  input: SchemaField[];
  /** Output field paths masked before the response is shown or stored. */
  maskedOutput: string[];
  /** Null when the operation names no customer record (reference data); confirmed at review. */
  binding: SubjectBinding | null;
  rateLimitPerMin: number;
  /** Each call waits for an approval token bound to the exact input. Always on for money movement. */
  requiresApproval: boolean;
  /** Money movement: the approver must differ from whoever requested or drafted the action. */
  fourEyes: boolean;
  /** Per-call ceiling in CAD, money movement only. */
  amountMax?: number;
  /** Writes carry `runId:actionId` as the idempotency key. */
  idempotent: boolean;
  calls24h: number;
  errorRate: number;
  p95Ms: number;
  /** Workflows with an active approval that includes this operation. */
  approvedWorkflows: number;
}

export type OperationPatch = Partial<Pick<ModuleOperation, 'enabled' | 'requiresApproval' | 'rateLimitPerMin' | 'binding' | 'amountMax' | 'description'>>;

export type ApprovalStatus = 'requested' | 'approved' | 'rejected' | 'expired' | 'revoked';

/** A workflow's permission to call some of a module's operations, bound to one major version. */
export interface ModuleApproval {
  id: string;
  workflowId: string;
  workflowName: string;
  environment: Environment;
  major: number;
  operations: string[];
  constraints?: string;
  requestedBy: string;
  justification: string;
  requestedAt: string;
  decidedBy?: string;
  decidedAt?: string;
  status: ApprovalStatus;
  expiresAt?: string;
  reason?: string;
}

export interface ApprovalRequestInput {
  workflowId: string;
  environment: Environment;
  operations: string[];
  expiresInDays: number;
  justification: string;
}

export type ChangeKind = 'added' | 'removed' | 'access_widened' | 'schema_changed' | 'binding_changed' | 'settings';

export interface OperationChange {
  operation: string;
  kind: ChangeKind;
  detail: string;
  /** Makes the version major: needs a new security review and new workflow approvals (00 A1). */
  major: boolean;
}

export interface ModuleVersion {
  version: string;
  major: number;
  status: 'draft' | 'in_review' | 'published' | 'deprecated' | 'revoked';
  publishedAt?: string;
  publishedBy: string;
  note: string;
  changes: OperationChange[];
  /** Workflows pinned to this version at their last publish. */
  pinnedBy: ModuleRef[];
  reachability: { environment: Environment; ok: boolean; checkedAt: string }[];
}

/** Security's review of one major version; minors within it reuse the decision. */
export interface SecurityReview {
  id: string;
  major: number;
  version: string;
  decision: 'pending' | 'approved' | 'changes_requested';
  requestedBy: string;
  requestedAt: string;
  reviewer?: string;
  decidedAt?: string;
  findings: string[];
  note?: string;
}

export type CredentialKind = 'oauth_client_credentials' | 'mtls' | 'api_key' | 'basic';

/** A pointer into the bank vault. No API returns the value. */
export interface ModuleCredential {
  id: string;
  environment: Environment;
  kind: CredentialKind;
  secretRef: string;
  setBy: string;
  setAt: string;
  rotateBy: string;
  status: 'ok' | 'rotate_soon' | 'overdue';
}

/** A sample run context the test console can act as: the workflow whose approval applies and the case's bound fields. */
export interface RunContextOption {
  id: string;
  label: string;
  workflowId: string;
  workflowName: string;
  caseId: string;
  bindings: Partial<Record<BindingSource, string>>;
}

export interface ToolModuleDetail extends ToolModule {
  ownerContacts: string[];
  auth: { kind: CredentialKind | 'none'; header?: string };
  timeoutMs: number;
  egressHosts: string[];
  dataClassification: 'public' | 'internal' | 'confidential' | 'restricted';
  operations: ModuleOperation[];
  /** Operation edits not yet published as a version. */
  pendingChanges: OperationChange[];
  approvals: ModuleApproval[];
  reviews: SecurityReview[];
  versions: ModuleVersion[];
  credentials: ModuleCredential[];
  runContexts: RunContextOption[];
}

export interface ModuleActivity {
  days: { date: string; count: number; errors: number; p95Ms: number }[];
  denied24h: number;
  recent: ToolCallRow[];
}

export interface ModuleTestInput {
  operation: string;
  contextId: string;
  /** `stub` returns the operation's schema-valid canned output; `sandbox` calls the system's test environment. */
  target: 'stub' | 'sandbox';
  input: Record<string, unknown>;
  /** Test only: the gateway issues a test approval token for this exact input instead of waiting for a person. */
  simulateApproval?: boolean;
}

export interface ModuleTestResult {
  /** `invalid`: the gateway allowed the call but the input failed the operation's schema, so nothing was sent. */
  decision: 'allow' | 'deny' | 'invalid';
  denyReason?: string;
  /** Plain-language reason for a denial. */
  denyMessage?: string;
  /** Per-field problems when `decision` is `invalid`. */
  invalid?: { field: string; message: string }[];
  /** Set when the call ran under a simulated approval; never valid outside the test environment. */
  testApprovalToken?: string;
  status: number;
  latencyMs: number;
  /** Inputs the gateway filled or checked from the run context. */
  bound: { arg: string; value: string; source: BindingSource }[];
  /** A write or money call would pause here for an approval token. */
  wouldPause: boolean;
  output: unknown;
  masked: string[];
  callId: string;
}

export type ModuleSource =
  | { kind: 'mcp'; url: string; secretRef?: string }
  | { kind: 'openapi'; specUrl?: string; fileName?: string; secretRef?: string }
  | { kind: 'catalog'; catalogId: string };

export interface DiscoveredOperation {
  name: string;
  description: string;
  access: ToolAccess;
  method?: HttpMethod;
  path?: string;
  /** Resource segment the picker groups by, e.g. `loans`. */
  group: string;
  input: SchemaField[];
}

export interface DiscoveryResult {
  type: ModuleType;
  system: string;
  suggestedName: string;
  version: string;
  endpoint: string;
  operations: DiscoveredOperation[];
  warnings: string[];
}

export interface HttpOperationInput {
  name: string;
  description: string;
  access: ToolAccess;
  method: HttpMethod;
  url: string;
  headers: { key: string; value: string }[];
  body?: string;
  secretRef?: string;
}

export interface ModuleInput {
  name: string;
  displayName: string;
  system: string;
  type: ModuleType;
  endpoint: string;
  secretRef?: string;
  catalogId?: string;
  /** Selected operations from discovery, with the access class the owner confirmed. */
  operations?: DiscoveredOperation[];
  http?: HttpOperationInput;
}

export interface CatalogItem {
  id: string;
  name: string;
  system: string;
  category: 'Core systems' | 'CRM' | 'Productivity' | 'Risk & compliance' | 'Internal';
  type: ModuleType;
  description: string;
  operations: number;
  auth: CredentialKind | 'none';
  owner: string;
  /** Set when a module from this item already exists. */
  moduleId?: string;
  /** The connected module's own approval state, so the card never says more than the module does. */
  moduleState?: ModuleApprovalState;
  available: boolean;
}
