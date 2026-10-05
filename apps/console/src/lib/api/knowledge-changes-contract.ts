import type { ChangeConflict, ChangeDecisionInput, ChangeListParams, ChangeViewCounts, KnowledgeChange } from '@/lib/types/knowledge-changes';
import type { ListResult } from '@/lib/types/query';

/**
 * Proposed edits to knowledge documents (curation, agents' suggested fixes, source syncs that changed a cited
 * passage). Only the document's owner can decide; approval re-runs the tests of every workflow that cited it.
 */
export interface KnowledgeChangesApi {
  list(params: ChangeListParams): Promise<ListResult<KnowledgeChange> & { viewCounts: ChangeViewCounts }>;
  get(id: string): Promise<KnowledgeChange>;
  decide(id: string, input: ChangeDecisionInput): Promise<KnowledgeChange>;
  resolveConflict(id: string, resolution: NonNullable<ChangeConflict['resolution']>): Promise<KnowledgeChange>;
}
