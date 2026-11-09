import type { ChangeDecisionInput, ChangeListParams, ChangeViewCounts, KnowledgeChange } from '@/lib/types/knowledge-changes';
import type { ListResult } from '@/lib/types/query';

/**
 * Knowledge changes: the versions syncs applied and the FAQ drafts waiting for review. Only FAQ drafts are decided,
 * by the knowledge owner of their source; an approved pair is searchable at once and cites its passage.
 */
export interface KnowledgeChangesApi {
  list(params: ChangeListParams): Promise<ListResult<KnowledgeChange> & { viewCounts: ChangeViewCounts }>;
  get(id: string): Promise<KnowledgeChange>;
  /** Approves or rejects FAQ drafts in one call; a draft already decided answers 409 `draft_decided`. */
  decide(input: ChangeDecisionInput): Promise<KnowledgeChange[]>;
  /** Edits a draft's question and answer; it still waits for review and its passage stays the source's. */
  edit(id: string, pair: { question: string; answer: string }): Promise<KnowledgeChange>;
}
