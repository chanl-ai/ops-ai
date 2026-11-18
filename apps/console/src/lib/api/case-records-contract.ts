import type { CaseRecord, CaseRecordDetail, CaseRecordPatch } from '@/lib/types/case-records';

/** The acting team's cases on agents-service (`/v1/cases`); the server filters and orders them. */
export interface CaseRecordsApi {
  get(id: string): Promise<CaseRecordDetail>;
  /** Each changed field lands on the timeline; closing or reopening needs cases.manage. */
  change(id: string, patch: CaseRecordPatch): Promise<CaseRecordDetail>;
  addNote(id: string, text: string): Promise<CaseRecordDetail>;
}
