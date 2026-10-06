import type { AuditEntry } from './governance';

/**
 * Integrations: the one place a bank system is connected. A connection holds how the platform authenticates
 * (a vault reference, never a value), the scopes granted, the owner and expiry, and its health. Knowledge
 * sources, tool modules and mailboxes reference a connection by id and show its status read-only.
 */
export type IntegrationKind =
  | 'm365'
  | 'sharepoint'
  | 'confluence'
  | 'salesforce'
  | 'core_banking'
  | 'case_management'
  | 'servicenow'
  | 'payments_hub'
  | 'internal_mcp'
  | 'gdrive'
  | 'zendesk'
  | 'github'
  | 'notion'
  | 'credit_bureau'
  | 'internal_api'
  | 'aws_s3'
  | 'azure_blob';

export type AuthMethod = 'oauth_consent' | 'service_principal' | 'api_key' | 'mtls';
/** `expiring`: healthy, but consent or credential ends within 30 days. Computed by the API. */
export type IntegrationStatus = 'healthy' | 'needs_reconnect' | 'expiring' | 'revoked' | 'error';
export type IntegrationView = 'all' | 'attention' | 'expiring' | 'revoked';
export type IntegrationFilters = { kind?: string[]; authMethod?: string[]; status?: string[]; ownerTeam?: string[] };
export type IntegrationViewCounts = Record<IntegrationView, number>;

/** What a dependant (source, tool module, mailbox) shows about the connection it uses. */
export interface ConnectionRef {
  id: string;
  name: string;
  kind: IntegrationKind;
  status: IntegrationStatus;
  expiresAt?: string;
}

export interface ScopeDef {
  id: string;
  label: string;
  /** Picker group, e.g. `Mail` or `Files`. */
  group: string;
  access: 'read' | 'write';
  /** Plain-language consequence of granting it. */
  description: string;
}

export interface UsedByCounts {
  sources: number;
  modules: number;
  mailboxes: number;
}

export interface Integration {
  id: string;
  name: string;
  kind: IntegrationKind;
  catalogId: string;
  authMethod: AuthMethod;
  /** Tenant, site or base URL the connection reaches. */
  instanceUrl: string;
  tenant?: string;
  /** Granted scope ids. */
  scopes: string[];
  /** e.g. "4 of 6 · read and write". */
  scopeSummary: string;
  ownerTeam: string;
  createdBy: string;
  createdAt: string;
  /** Consent or credential expiry. */
  expiresAt?: string;
  /** When the vault credential must be rotated; OAuth consent has none. */
  rotateBy?: string;
  /** Vault path the gateway resolves; no API returns the secret. */
  credentialRef?: string;
  status: IntegrationStatus;
  lastCheckedAt: string;
  lastError?: string;
  usedBy: UsedByCounts;
}

export type DependantType = 'source' | 'tool_module' | 'mailbox';
export type Tone = 'ok' | 'warn' | 'bad' | 'muted';

export interface Dependant {
  type: DependantType;
  id: string;
  name: string;
  href: string;
  owner: string;
  status: string;
  tone: Tone;
  /** What stops working if the connection is revoked. */
  stops: string;
}

export interface HealthCheck {
  id: string;
  at: string;
  ok: boolean;
  latencyMs: number;
  message: string;
  /** `Scheduled` or the person who ran it. */
  by: string;
}

export interface ScopeRequest {
  id: string;
  scopes: string[];
  justification: string;
  requestedBy: string;
  requestedAt: string;
  /** The system owner who decides it. */
  approver: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface ConnectionActivity {
  id: string;
  at: string;
  kind: 'sync' | 'call';
  label: string;
  detail: string;
  ok: boolean;
  href: string;
}

export type FixAction = 'reconnect' | 'rotate' | 'recheck';

export interface IntegrationDetail extends Integration {
  /** Every scope the system offers, granted or not. */
  availableScopes: ScopeDef[];
  checks: HealthCheck[];
  scopeRequests: ScopeRequest[];
  dependants: Dependant[];
  activity: ConnectionActivity[];
  audit: AuditEntry[];
  /** The action that clears `lastError`. */
  fix?: { action: FixAction; label: string };
  /** The system owner who approves scope requests. */
  systemOwner: string;
}

export type CatalogCategory = 'Core systems' | 'Productivity' | 'Knowledge' | 'CRM' | 'Risk & compliance' | 'Internal';

export interface CatalogSystem {
  id: string;
  name: string;
  kind: IntegrationKind;
  category: CatalogCategory;
  description: string;
  /** Auth methods this system accepts, the first one recommended. */
  authMethods: AuthMethod[];
  scopes: ScopeDef[];
  /** e.g. `northfield.sharepoint.com`. */
  instanceHint: string;
  /** Team that owns the system and approves scope requests. */
  owner: string;
  available: boolean;
  unavailableReason?: string;
  /** Connections of this system the current team can see. */
  connected: number;
  /** Set when exactly one connection exists. */
  connectionId?: string;
}

export interface ConnectInput {
  catalogId: string;
  name: string;
  instanceUrl: string;
  authMethod: AuthMethod;
  scopes: string[];
  /** Required for service principal, API key and mTLS. */
  credentialRef?: string;
  /** OAuth only: the admin who granted consent. */
  consentBy?: string;
  ownerTeam: string;
  expiresAt: string;
}

export interface RevokeImpact {
  dependants: Dependant[];
  sources: number;
  modules: number;
  mailboxes: number;
}
