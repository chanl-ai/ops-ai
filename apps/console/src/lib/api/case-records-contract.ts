import type { CaseRecord, CaseRecordDetail, CaseRecordFilters, CaseRecordPatch } from '@/lib/types/case-records';
import type { ListResult } from '@/lib/types/query';

/** The acting team's cases on agents-service (`/v1/cases`, c-128); the server filters and orders them. */
export interface CaseRecordsApi {
  /** Soonest resolution deadline first; `overdue` keeps open ones past it, leaving out one that waits on the customer. */
  list(params: { page: number; pageSize: number } & CaseRecordFilters): Promise<ListResult<CaseRecord>>;
  get(id: string): Promise<CaseRecordDetail>;
  /** Each changed field lands on the timeline; closing or reopening needs cases.manage. */
  change(id: string, patch: CaseRecordPatch): Promise<CaseRecordDetail>;
  addNote(id: string, text: string): Promise<CaseRecordDetail>;
}
