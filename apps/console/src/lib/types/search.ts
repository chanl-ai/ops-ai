/** Record kinds the command palette searches on the server. Pages and actions are listed by the client. */
export type SearchGroup = 'workflows' | 'agents' | 'cases' | 'knowledge' | 'chats';

export interface SearchHit {
  id: string;
  group: SearchGroup;
  title: string;
  /** Second line: owner, status or the record's parent. */
  detail?: string;
  href: string;
}

export interface SearchResults {
  query: string;
  /** Groups with at least one hit, in display order. `total` counts every match, `hits` holds the first few. */
  groups: { group: SearchGroup; hits: SearchHit[]; total: number }[];
}
