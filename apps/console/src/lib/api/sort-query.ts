import type { ListParams } from '@/lib/types/query';

/**
 * The list's order on the shared list contract (`sortBy`, `sortOrder`), added to a query a client builds by hand, so a
 * header click orders the whole list on the server and not only the page the table holds.
 */
export function addSort(q: URLSearchParams, p: Pick<ListParams, 'sortBy' | 'sortOrder'>): URLSearchParams {
  if (p.sortBy) q.set('sortBy', p.sortBy);
  if (p.sortOrder) q.set('sortOrder', p.sortOrder);
  return q;
}
