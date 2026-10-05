import type { BulkResult } from '@/lib/types/domain';
import type { ListParams, ListResult } from '@/lib/types/query';
import type {
  ApprovalRequestInput,
  CatalogItem,
  DiscoveryResult,
  ModuleActivity,
  ModuleApproval,
  ModuleFilters,
  ModuleInput,
  ModuleSource,
  ModuleStats,
  ModuleTestInput,
  ModuleTestResult,
  ModuleView,
  ModuleViewCounts,
  OperationPatch,
  ToolModule,
  ToolModuleDetail,
} from '@/lib/types/tool-modules';

/** Tool modules behind the data gateway (spec 03 §4–5). Lists are scoped to the current team. */
export interface ToolModulesApi {
  list(params: ListParams<ModuleFilters> & { view: ModuleView }): Promise<ListResult<ToolModule> & { stats: ModuleStats; viewCounts: ModuleViewCounts }>;
  get(id: string): Promise<ToolModuleDetail>;
  catalog(): Promise<CatalogItem[]>;
  /** Reads an MCP server's tool list or an OpenAPI document without saving anything. */
  discover(source: ModuleSource): Promise<DiscoveryResult>;
  /** Saves a draft module; it needs a security review before any workflow can be approved for it. */
  create(input: ModuleInput): Promise<ToolModuleDetail>;
  remove(id: string): Promise<void>;
  /** Modules some workflow still holds an approval for are skipped. */
  bulkRemove(ids: string[]): Promise<BulkResult>;
  /** Stages an operation change; it reaches workflows only when published as a version. */
  updateOperation(id: string, operationId: string, patch: OperationPatch): Promise<ToolModuleDetail>;
  /** Publishes staged changes. A major version opens a security review and needs new workflow approvals. */
  publishVersion(id: string, note: string): Promise<ToolModuleDetail>;
  discardChanges(id: string): Promise<ToolModuleDetail>;
  requestReview(id: string, note: string): Promise<ToolModuleDetail>;
  requestApproval(id: string, input: ApprovalRequestInput): Promise<ModuleApproval>;
  /** Owner team only, and never the requester. */
  decideApproval(id: string, approvalId: string, decision: 'approved' | 'rejected', reason?: string): Promise<ModuleApproval>;
  revokeApprovals(id: string, approvalIds: string[], reason: string): Promise<BulkResult>;
  setCredentialRef(id: string, credentialId: string, secretRef: string): Promise<ToolModuleDetail>;
  test(id: string, input: ModuleTestInput): Promise<ModuleTestResult>;
  activity(id: string): Promise<ModuleActivity>;
}
