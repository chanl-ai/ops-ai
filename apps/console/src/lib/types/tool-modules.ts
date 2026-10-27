import type { ToolAccess } from './domain';
import type { ToolCallRow } from './governance';
import type { ConnectionRef } from './integrations';

/**
 * Tool modules (spec 03 §4.1): one system connected once, holding the operations agents call. A module version is
 * security-reviewed once per major version (00 A1) and each workflow uses it only under an approval with expiry.
 */
export type ModuleType = 'mcp' | 'openapi' | 'http' | 'code';
export type ModuleStatus = 'draft' | 'in_review' | 'published' | 'revoked';
/** Computed by the API from the security review, workflow approvals and drift. */
export type ModuleApprovalState = 'draft' | 'approved' | 'needs_approval' | 'expiring' | 'expired';
/** `expiring` holds modules whose approvals expire within 30 days; already expired ones have their own view. */
/** `security_review`: modules with a security review waiting on Security (the Reviews page's Tool modules tab). */
export type ModuleView = 'all' | 'needs_approval' | 'expiring' | 'expired' | 'failing' | 'security_review';
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
  /** The integration whose credential the gateway uses; null for modules served inside the gateway. */
  connectionId?: string;
  connection: ConnectionRef | null;
  updatedAt: string;
  /** The review waiting on Security, if any. */
  pendingReview?: { id: string; version: string; requestedBy: string; requestedAt: string } | null;
  /** Distinct secrets the operations read that the tenant has not set. */
  unsetSecrets?: number;
}

export type ModuleFilters = { type?: string[]; access?: string[]; approvalState?: string[] };
export type ModuleViewCounts = Record<ModuleView, number>;

export interface ModuleStats {
  modules: number;
  operations: number;
  calls24h: number;
  /** Failed calls over all calls, last 24h. */
  errorRate: number;
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
  /** Sent when a call leaves this optional field out. */
  default?: string | number | boolean;
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
  /** How the gateway runs it; only `http` operations have a call a builder edits. */
  executor: 'http' | 'mcp' | 'stub' | 'local';
  method?: HttpMethod;
  /** After the module endpoint; the origin is always the endpoint's. */
  path?: string;
  /** Literal values or `{{NAME}}` secret references; a literal credential is refused on save. */
  headers: { key: string; value: string }[];
  /** JSON template with `{{arg}}` placeholders. */
  body?: string;
  /** Jinja2 template over the parsed response as `data`; failing at call time returns the raw answer with an error. */
  responseTransform?: string;
  /** The mock response: what a call against the mock, and every write in the test console, answers. Reviewed like any
   * edit (c-088). */
  stub?: unknown;
  /** This operation's limit, 1000 to 120000; unset uses the module's timeout. */
  timeoutMs?: number;
  input: SchemaField[];
  /** Output field paths masked before the response is shown or stored. */
  maskedOutput: string[];
  /** Null when the operation names no customer record (reference data); confirmed at review. */
  binding: SubjectBinding | null;
  rateLimitPerMin: number;
  /** Each call waits for an approval token bound to the exact input. */
  requiresApproval: boolean;
  /** A write's approval policy: how many distinct people of the run's team approve each call (c-509). */
  approvers: 1 | 2;
  /** Approving asks the approver to step up (implied by two approvers). */
  stepUp?: boolean;
  /** Each `{{NAME}}` the headers or path read, and whether the tenant has set it. */
  /** `set`: the module's own team holds it, the only secrets a call of this module reads (c-509). */
  secrets?: { name: string; set: boolean; available?: boolean }[];
  /** Per-call ceiling in CAD. */
  amountMax?: number;
  /** Writes carry `runId:actionId` as the idempotency key. */
  idempotent: boolean;
  calls24h: number;
  errorRate: number;
  p95Ms: number;
  /** Workflows with an active approval that includes this operation. */
  approvedWorkflows: number;
}

/**
 * A staged edit. Method, path or body changes are major; headers, transform and timeout minor. `responseTransform` or
 * `timeoutMs` null clears it. Calls keep the published call until the change is published.
 */
export type OperationPatch = Partial<Pick<ModuleOperation, 'enabled' | 'requiresApproval' | 'rateLimitPerMin' | 'binding' | 'amountMax' | 'description' | 'method' | 'path' | 'headers' | 'body' | 'approvers' | 'stepUp' | 'access' | 'input' | 'stub'>> & {
  responseTransform?: string | null;
  timeoutMs?: number | null;
};

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
  /** The Human Tasks review deciding the request (c-166); absent on requests made before they went there. */
  reviewId?: string;
  /** The team whose reviewers decide it. */
  deciderTeam?: string;
}

/** A workflow's access to one module, as Access › Tool access lists it across modules (c-144). */
export interface ToolGrant extends ModuleApproval {
  moduleId: string;
  moduleName: string;
}

export type GrantView = 'active' | 'expiring' | 'requested' | 'expired' | 'ended' | 'all';

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
  /** Its review, a publish request decided in Human Tasks (c-163): the request id and when it was asked for. */
  reviewId?: string;
  requestedAt?: string;
  /** Who decided it, and for a no the reason, shown as the finding. */
  reviewer?: string;
  finding?: string;
}

export type CredentialKind = 'oauth_client_credentials' | 'mtls' | 'api_key' | 'basic';

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
  /** What the caller may do with it, by the routes' own checks (c-186); absent before the API sends them. */
  canEdit?: boolean;
  canDelete?: boolean;
  canPublish?: boolean;
  ownerContacts: string[];
  auth: { kind: CredentialKind | 'none'; header?: string };
  timeoutMs: number;
  egressHosts: string[];
  dataClassification: 'public' | 'internal' | 'confidential' | 'restricted';
  operations: ModuleOperation[];
  /** Operation edits not yet published as a version. */
  pendingChanges: OperationChange[];
  approvals: ModuleApproval[];
  versions: ModuleVersion[];
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
  /** The workbench's unsaved definition, tried without staging it; agents never see it (c-088). */
  /** `responseTransform: null` runs with no transform; left out, the operation's own. */
  draft?: { responseTransform?: string | null; stub?: unknown };
  /** Secret values for this run only, never stored; a secret not given here is read from the tenant's secrets. */
  secretValues?: Record<string, string>;
}

/** The request the gateway sent, secret values masked. */
export interface TestRequest {
  method: string;
  url: string;
  headers: { key: string; value: string }[];
  body?: string;
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
  /** Test environment: true when the answer is the stub (every write), false when a read reached the system. */
  stubbed?: boolean;
  /** Test environment: the host a read reached. */
  reachedHost?: string;
  /** Inputs the gateway filled or checked from the run context. */
  bound: { arg: string; value: string; source: BindingSource }[];
  /** A write would pause here for an approval token. */
  wouldPause: boolean;
  output: unknown;
  masked: string[];
  callId: string;
  /** What was sent; absent when nothing was (a denial, invalid input). */
  request?: TestRequest;
  /** The answer before the transform; `output` is after it. */
  rawResponse?: unknown;
  /** The transform's error when it failed; `output` is then the raw answer. */
  transformError?: string;
  /** What the gateway did, in order, with the time since the call started. */
  log?: { atMs: number; message: string }[];
}

export type ModuleSource =
  | { kind: 'mcp'; url: string }
  | { kind: 'openapi'; specUrl?: string; fileName?: string; /** Uploaded spec, from the Files API. */ fileId?: string };

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
}

export interface ModuleInput {
  name: string;
  displayName: string;
  system: string;
  type: ModuleType;
  endpoint: string;
  /**
   * Where `operations` were discovered. The service re-reads it and takes each operation's method, path, inputs and
   * headers from there, so only the names and the access class the owner confirmed come from the caller.
   */
  source?: ModuleSource;
  /** Selected operations from discovery, with the access class the owner confirmed. */
  operations?: DiscoveredOperation[];
  http?: HttpOperationInput;
  /** Import without a naming step: a taken name gets a numeric suffix instead of a 409. */
  uniqueName?: boolean;
}

/** "New module": a name and a type. It saves a draft with no operations and no connection; the page does the rest. */
export interface BlankModuleInput {
  displayName: string;
  /** Kebab-case name workflows pin; cannot change once a workflow is approved for the module. */
  name: string;
  type: ModuleType;
  description?: string;
}

export interface ModuleDetailsPatch {
  displayName?: string;
  description?: string;
}

/** Operations chosen from an MCP server or OpenAPI document, appended to an existing module. */
export interface ImportOperationsInput {
  source: ModuleSource;
  operations: DiscoveredOperation[];
}
