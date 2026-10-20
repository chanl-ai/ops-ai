import type { Option, OptionsPage, OptionsParams } from '@/lib/types/query';

/** The query string every `/options` route takes: search, cursor and limit, or the stored ids to label. */
export function optionsQs(p: OptionsParams): string {
  const q = new URLSearchParams();
  if (p.ids) for (const id of p.ids) q.append('ids', id);
  else {
    if (p.search) q.set('search', p.search);
    if (p.cursor) q.set('cursor', p.cursor);
  }
  if (p.limit) q.set('limit', String(p.limit));
  return q.toString();
}

/** One mock `/options` page over options already in memory, with the same search, cursor and ids rules as the routes. */
export function pageOptions(all: Option[], p: OptionsParams): OptionsPage {
  if (p.ids) {
    const wanted = new Set(p.ids);
    return { data: all.filter((o) => wanted.has(o.id)), nextCursor: null };
  }
  const q = (p.search ?? '').trim().toLowerCase();
  const hits = all.filter((o) => `${o.label} ${o.hint ?? ''}`.toLowerCase().includes(q));
  const limit = p.limit ?? 25;
  const offset = Number(p.cursor ?? 0) || 0;
  return { data: hits.slice(offset, offset + limit), nextCursor: offset + limit < hits.length ? String(offset + limit) : null };
}
