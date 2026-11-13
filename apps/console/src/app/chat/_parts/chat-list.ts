import type { ChatThreadListParams } from '@/lib/types/chat';

const PAGE = 30;
/** Chats shown under the pinned ones before a search or "Show more chats". */
export const RECENT = 5;
const STATES = ['active', 'pinned'];

export type FlagState = 'on' | 'off' | 'loading';

/**
 * Where the person's list of chats is drawn. With the single sidebar (area tabs off) it is a column on the chat pages,
 * and the main sidebar only links to Chat; with area tabs on it stays in the sidebar. Nothing is drawn while the flag
 * loads, so a column never shows and then disappears.
 */
export function chatListPlace(areaTabs: FlagState, pathname: string): 'sidebar' | 'column' | 'none' {
  if (areaTabs === 'loading') return 'none';
  if (areaTabs === 'on') return 'sidebar';
  return pathname === '/chat' || (pathname.startsWith('/chat/') && pathname !== '/chat/conversations') ? 'column' : 'none';
}

/**
 * The list's request. By default the pinned chats and the newest few, in one response with no next page. A search or
 * "Show more chats" drops `recent`, since only a paged response carries a cursor, and the server does the searching.
 */
export function chatListParams(search: string, more: boolean): Omit<ChatThreadListParams, 'page' | 'cursor'> {
  const q = search.trim();
  if (q) return { pageSize: PAGE, search: q, filters: { state: STATES } };
  if (more) return { pageSize: PAGE, filters: { state: STATES } };
  return { pageSize: PAGE, recent: RECENT, filters: { state: STATES } };
}
