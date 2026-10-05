import type {
  ActionDecision,
  CaseAction,
  CaseDetail,
  CaseFilters,
  CaseRow,
  CaseStats,
  CaseView,
  CaseViewCounts,
  EmailWorkflowConfig,
  SampleMailInput,
  SampleMailResult,
} from '@/lib/types/cases';
import type { BulkResult } from '@/lib/types/domain';
import type { ListParams, ListResult } from '@/lib/types/query';

/** Email-to-workflow: the ops workbench of cases, and the sample-mail test for email workflow configuration. */
export interface CasesApi {
  list(params: ListParams<CaseFilters> & { view: CaseView }): Promise<ListResult<CaseRow> & { viewCounts: CaseViewCounts; stats: CaseStats }>;
  get(id: string): Promise<CaseDetail>;
  /** Corrects an extracted field; logged as an edit on the case. */
  setField(id: string, key: string, value: string): Promise<CaseDetail>;
  assign(ids: string[], assignee: string): Promise<BulkResult>;
  close(ids: string[], reason: string): Promise<BulkResult>;
  /** Approve or reject one drafted action. Approval runs the action once its approvals are complete. */
  decideAction(caseId: string, actionId: string, input: { decision: ActionDecision; reason?: string }): Promise<CaseAction>;
  /** Replaces a drafted action's input (tool arguments or reply text) before approval. */
  editAction(caseId: string, actionId: string, input: string): Promise<CaseAction>;
  /** Classifies a sample email against a configuration (normally the workflow draft) without opening a case. */
  testSampleMail(config: EmailWorkflowConfig, input: SampleMailInput): Promise<SampleMailResult>;
  /** Team queues and the people who can be assigned cases. */
  queues(): Promise<{ queues: string[]; assignees: string[]; approverGroups: string[] }>;
}
