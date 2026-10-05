import type { BulkResult } from '@/lib/types/domain';
import type { ConditionInput, ConditionStatus, ModelEntry, ModelEntryDetail, ModelRiskFilters, ModelRiskOptions, ModelRiskStats, ModelRiskView, ModelRiskViewCounts, TierChangeInput } from '@/lib/types/model-risk';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * Model risk inventory. Validation decisions are made in the Reviews queue (`model_validation` reviews), so
 * this API only requests them. Tier changes, validation decisions and condition changes are audited.
 */
export interface ModelRiskApi {
  list(params: ListParams<ModelRiskFilters> & { view: ModelRiskView }): Promise<ListResult<ModelEntry> & { viewCounts: ModelRiskViewCounts; stats: ModelRiskStats }>;
  get(id: string): Promise<ModelEntryDetail>;
  /** Opens a validation review for each entry; entries with one already open are skipped. */
  requestValidation(ids: string[], note?: string): Promise<BulkResult>;
  /** `date` is yyyy-mm-dd. */
  setNextReview(ids: string[], date: string): Promise<BulkResult>;
  /** Low and medium apply at once; high and critical open a second-line review and apply when Model Risk approves. */
  changeTier(id: string, input: TierChangeInput): Promise<ModelEntryDetail>;
  addCondition(id: string, input: ConditionInput): Promise<ModelEntryDetail>;
  setConditionStatus(id: string, conditionId: string, status: ConditionStatus, reason: string): Promise<ModelEntryDetail>;
  options(): Promise<ModelRiskOptions>;
}
