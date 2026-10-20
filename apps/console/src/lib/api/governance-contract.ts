import type { BulkResult } from '@/lib/types/domain';
import type {
  AccessGrant,
  AccessOptions,
  AccessStats,
  AuditEntry,
  AuditFilters,
  AuditView,
  AuditViewCounts,
  GrantFilters,
  GrantInput,
  GrantView,
  RoleAssignment,
  RoleFilters,
  RoleInput,
  ToolCallDetail,
  ToolCallFilters,
  ToolCallRow,
  ToolCallStats,
  WorkflowIdentity,
} from '@/lib/types/governance';
import type { ListParams, ListResult } from '@/lib/types/query';

/** Logs (gateway calls, audit) and access (workflow identities, grants, who may author, approve and publish). */
export interface GovernanceApi {
  toolCalls: {
    list(params: ListParams<ToolCallFilters>): Promise<ListResult<ToolCallRow> & { stats: ToolCallStats }>;
    get(id: string): Promise<ToolCallDetail>;
  };
  audit: {
    list(params: ListParams<AuditFilters> & { view: AuditView }): Promise<ListResult<AuditEntry> & { viewCounts: AuditViewCounts }>;
  };
  access: {
    identities(params: ListParams): Promise<ListResult<WorkflowIdentity> & { stats: AccessStats }>;
    grants(params: ListParams<GrantFilters> & { view: GrantView }): Promise<ListResult<AccessGrant> & { viewCounts: Record<GrantView, number> }>;
    grant(input: GrantInput): Promise<AccessGrant>;
    /** Revokes at once; runs already holding a token finish their current call. */
    revoke(ids: string[], reason: string): Promise<BulkResult>;
    /** Pushes the expiry of each grant out by `days` from today. */
    extend(ids: string[], days: number): Promise<BulkResult>;
    roles(params: ListParams<RoleFilters>): Promise<ListResult<RoleAssignment>>;
    assignRole(input: RoleInput): Promise<RoleAssignment>;
    removeRoles(ids: string[]): Promise<BulkResult>;
    options(): Promise<AccessOptions>;
  };
}
