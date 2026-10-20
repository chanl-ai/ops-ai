import type { AssuranceFilters, AssuranceResult, AssuranceRowOf, AssuranceTab } from '@/lib/types/assurance';
import type { FileRecord } from '@/lib/types/files';
import type { ListParams } from '@/lib/types/query';

/**
 * Assurance: one read over suites, eval runs, publish gates, sealed evidence and judges. Every call returns the
 * page's stats and per-tab counts with the requested tab's rows. Draft cases are added by review decisions
 * (`ReviewDecisionInput.addTestCase`), not through this API.
 */
export interface AssuranceApi {
  list<K extends AssuranceTab>(params: ListParams<AssuranceFilters> & { tab: K }): Promise<AssuranceResult<AssuranceRowOf[K]>>;
  /** Writes the sealed bundle as an export file in Files; the bundle itself never changes. */
  exportBundle(id: string): Promise<FileRecord>;
}
