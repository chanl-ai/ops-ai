import type { SearchHit, SearchResults } from '@/lib/types/search';

/** Server-side search behind the ⌘K palette. Every result is limited to the current team. */
export interface SearchApi {
  query(q: string): Promise<SearchResults>;
  /** Records the user opened, newest first. */
  recent(): Promise<SearchHit[]>;
  /** Remembers that the user opened a record from the palette. */
  visit(hit: SearchHit): Promise<void>;
}
