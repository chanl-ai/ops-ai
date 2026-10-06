/**
 * Governance: what the gateways did (tool and model calls), who changed what (audit), and what each workflow
 * identity may reach (access). Every list is scoped to the current team by the API.
 */

// ── Gateway calls ──────────────────────────────────────────────────────────

/** The data gateway fronts bank systems and knowledge; the AI gateway fronts models. */
export type GatewayKind = 'data' | 'ai';
export type CallOperation = 'read' | 'write' | 'money_movement' | 'completion';
/** How a write was authorised: a person's approval token, a gate policy that auto-approves, or none (reads, model calls). */
export type ApprovalKind = 'person' | 'policy' | 'none';
export type CallStatus = 'ok' | 'error' | 'denied' | 'awaiting_approval';

export interface CallApproval {
  kind: ApprovalKind;
  /** Approval token the gateway checked before running the write. */
  tokenId?: string;
  by?: string;
  at?: string;
  reviewId?: string;
  policyName?: string;
  policyVersion?: number;
}

export interface ToolCallRow {
  id: string;
  at: string;
  gateway: GatewayKind;
  workflowId: string;
  workflowName: string;
  agentSlug: string;
  agentName: string;
  runId: string;
  caseId?: string;
  /** `place_wire_hold` for a tool, the model alias for a model call. */
  target: string;
  /** Bank system or module for a tool; the resolved model for a model call. */
  system: string;
  operation: CallOperation;
  /** The record the call was bound to, e.g. `Wire W-88213`. */
  record?: string;
  approval: CallApproval;
  status: CallStatus;
  latencyMs: number;
  /** Model calls only. */
  tokens?: { input: number; output: number };
  /** Model calls only, in CAD. */
  cost?: number;
}

export interface ToolCallDetail extends ToolCallRow {
  requestId: string;
  /** Principal the gateway saw, e.g. the workflow identity. */
  identity: string;
  request: unknown;
  response: unknown;
  /** Field paths masked before the payload was stored. */
  redacted: string[];
  /** The gate policy evaluated for this call, with the version in force at the time. */
  policy: { name: string; version: number; rule: string } | null;
  error?: string;
}

export type ToolCallFilters = { gateway?: string[]; operation?: string[]; approval?: string[]; status?: string[]; workflowId?: string[] };

export interface ToolCallStats {
  failed: number;
  errorRate: number;
  /** Refused at the gateway: no grant, or an expired one. */
  denied: number;
  writesApprovedByPerson: number;
  awaitingApproval: number;
  p95Ms: number;
}

// ── Audit ──────────────────────────────────────────────────────────────────

export type AuditAction = 'created' | 'edited' | 'published' | 'approved' | 'rejected' | 'restored' | 'deleted' | 'granted' | 'revoked' | 'connected' | 'login' | 'uploaded' | 'downloaded' | 'legal_hold';
export type AuditTargetType =
  | 'workflow'
  | 'agent'
  | 'tool'
  | 'knowledge_base'
  | 'source'
  | 'deployment'
  | 'gate'
  | 'review'
  | 'access_grant'
  | 'role'
  | 'member'
  | 'api_key'
  | 'webhook'
  | 'mailbox'
  | 'integration'
  | 'notifications'
  | 'session'
  | 'model'
  | 'file'
  | 'storage';

export interface AuditActor {
  kind: 'person' | 'workflow';
  name: string;
  /** Email for a person, principal for a workflow identity. */
  detail: string;
}

export interface AuditEntry {
  id: string;
  at: string;
  actor: AuditActor;
  action: AuditAction;
  target: { type: AuditTargetType; name: string; href?: string };
  teamId: string;
  team: string;
  summary: string;
  diff: { field: string; before?: string; after?: string }[];
  reason?: string;
  requestId: string;
}

export type AuditView = 'all' | 'publishes' | 'access' | 'deletions';
export type AuditFilters = { action?: string[]; targetType?: string[]; actorKind?: string[]; teamId?: string[] };
export type AuditViewCounts = Record<AuditView, number>;

// ── Access ─────────────────────────────────────────────────────────────────

/** One identity per workflow: the principal its runs use at the data and AI gateways. */
export interface WorkflowIdentity {
  id: string;
  workflowId: string;
  workflowName: string;
  principal: string;
  owner: string;
  team: string;
  status: 'active' | 'suspended';
  grants: number;
  expiringSoon: number;
  moneyMovement: boolean;
  lastUsedAt?: string;
}

export type ResourceKind = 'module' | 'knowledge_base';
export type GrantScope = 'read' | 'write' | 'money_movement';
export type GrantStatus = 'active' | 'expiring' | 'expired';

export interface AccessGrant {
  id: string;
  identityId: string;
  workflowId: string;
  workflowName: string;
  resourceKind: ResourceKind;
  /** `Payments Hub · place_wire_hold` or a knowledge base name. */
  resource: string;
  scope: GrantScope;
  grantedBy: string;
  grantedAt: string;
  /** Every grant expires (spec 03); renewal is a new decision. */
  expiresAt: string;
  status: GrantStatus;
  reason?: string;
}

/** Expiring = active grants inside the expiry window; expired grants have their own view. */
export type GrantView = 'all' | 'expiring' | 'expired';
export type GrantFilters = { workflowId?: string[]; resourceKind?: string[]; scope?: string[]; status?: string[] };

export interface GrantInput {
  workflowId: string;
  resourceKind: ResourceKind;
  resource: string;
  scope: GrantScope;
  /** Required: grants without expiry are not allowed. */
  expiresInDays: number;
  reason: string;
}

export type Capability = 'author' | 'approve' | 'publish';

/** Who may author, approve and publish workflows in a team. */
export interface RoleAssignment {
  id: string;
  principal: string;
  principalKind: 'person' | 'group';
  /** People in the group; 1 for a person. */
  members: number;
  teamId: string;
  team: string;
  capabilities: Capability[];
  addedBy: string;
  addedAt: string;
}

export type RoleFilters = { principalKind?: string[]; capabilities?: string[]; teamId?: string[] };

export interface RoleInput {
  principal: string;
  principalKind: 'person' | 'group';
  teamId: string;
  capabilities: Capability[];
}

export interface AccessStats {
  identities: number;
  activeGrants: number;
  expiringSoon: number;
  moneyMovementGrants: number;
}

export interface AccessOptions {
  workflows: { id: string; name: string }[];
  modules: { value: string; system: string; access: GrantScope }[];
  knowledgeBases: string[];
  people: string[];
  groups: string[];
  teams: { id: string; name: string }[];
}
