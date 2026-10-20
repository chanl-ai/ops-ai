import type { ListParams, ListResult } from '@/lib/types/query';
import type { WikiCollection, WikiFilters, WikiPage, WikiPageDetail, WikiView, WikiViewCounts } from '@/lib/types/wiki';

/** The Wiki: pages and documents with versions and a verified mark, grouped in collections. */
export interface WikiApi {
  list(params: ListParams<WikiFilters> & { view: WikiView }): Promise<ListResult<WikiPage> & { viewCounts: WikiViewCounts }>;
  get(id: string): Promise<WikiPageDetail>;
  /** Marks the current version verified by the caller; a remembered page becomes searchable by every reader. */
  verify(id: string): Promise<WikiPageDetail>;
  collections(): Promise<WikiCollection[]>;
  /** One page of the collections whose name or description matches the search. */
  collectionsPage(p: ListParams): Promise<ListResult<WikiCollection>>;
}
