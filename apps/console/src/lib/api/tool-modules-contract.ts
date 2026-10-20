import type { BulkResult } from '@/lib/types/domain';
import type { ListParams, ListResult } from '@/lib/types/query';
import type {
  ApprovalRequestInput,
  BlankModuleInput,
  HttpOperationInput,
  ImportOperationsInput,
  ModuleDetailsPatch,
  DiscoveryResult,
  ModuleActivity,
  GrantView,
  ModuleApproval,
  ToolGrant,
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
  /** Every workflow's access across the modules the team sees, one view at a time; `facets.view` counts each view. */
  grants(params: { view: GrantView; search?: string; page: number; pageSize: number }): Promise<ListResult<ToolGrant>>;
  list(params: ListParams<ModuleFilters> & { view: ModuleView }): Promise<ListResult<ToolModule> & { stats: ModuleStats; viewCounts: ModuleViewCounts }>;
  get(id: string): Promise<ToolModuleDetail>;
  /** Reads an MCP server's tool list or an OpenAPI document without saving anything. */
  discover(source: ModuleSource): Promise<DiscoveryResult>;
  /** Saves a draft module; it needs a security review before any workflow can be approved for it. */
  create(input: ModuleInput): Promise<ToolModuleDetail>;
  /** Saves a draft with a name and a type only: no operations, no connection. Drafts skip review gates until publish. */
  createBlankModule(input: BlankModuleInput): Promise<ToolModuleDetail>;
  updateModuleDetails(id: string, patch: ModuleDetailsPatch): Promise<ToolModuleDetail>;
  /** One operation built by hand (method, URL, headers, body); works for every module type. */
  addOperation(id: string, input: HttpOperationInput): Promise<ToolModuleDetail>;
  /** Appends operations chosen from discovery; marks drift when the server no longer lists ones the module has. */
  importOperations(id: string, input: ImportOperationsInput): Promise<ToolModuleDetail>;
  /** Attaches or changes the integration the gateway authenticates through; null detaches it (drafts only). */
  setConnection(id: string, connectionId: string | null): Promise<ToolModuleDetail>;
  remove(id: string): Promise<void>;
  /** Modules some workflow still holds an approval for are skipped. */
  bulkRemove(ids: string[]): Promise<BulkResult>;
  /** Stages an operation change; it reaches workflows only when published as a version. */
  updateOperation(id: string, operationId: string, patch: OperationPatch): Promise<ToolModuleDetail>;
  /** Publishes staged changes. A major version opens a security review and needs new workflow approvals. */
  publishVersion(id: string, note: string): Promise<ToolModuleDetail>;
  discardChanges(id: string): Promise<ToolModuleDetail>;
  /** Opens the version's review in Human Tasks, where it is decided (c-163). */
  requestReview(id: string, note: string): Promise<ToolModuleDetail>;
  requestApproval(id: string, input: ApprovalRequestInput): Promise<ModuleApproval>;
  /** Owner team only, and never the requester. */
  decideApproval(id: string, approvalId: string, decision: 'approved' | 'rejected', reason?: string): Promise<ModuleApproval>;
  revokeApprovals(id: string, approvalIds: string[], reason: string): Promise<BulkResult>;
  test(id: string, input: ModuleTestInput): Promise<ModuleTestResult>;
  activity(id: string): Promise<ModuleActivity>;
}
