import type { BulkResult } from '@/lib/types/domain';
import type { ListParams, ListResult } from '@/lib/types/query';

import { ApiError } from '../contract';

/**
 * Shared mock transport. Append `?mock=slow`, `?mock=error` or `?mock=empty` to any URL to see the loading,
 * error and empty states; the choice sticks for the browser tab until `?mock=off`.
 */
export type Mode = 'normal' | 'slow' | 'error' | 'empty';

export function mode(): Mode {
  if (typeof window === 'undefined') return 'normal';
  try {
    const q = new URLSearchParams(window.location.search).get('mock');
    if (q === 'off') sessionStorage.removeItem('ops-mock-mode');
    else if (q === 'slow' || q === 'error' || q === 'empty') sessionStorage.setItem('ops-mock-mode', q);
    return (sessionStorage.getItem('ops-mock-mode') as Mode | null) ?? 'normal';
  } catch {
    return 'normal';
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function respond<T>(fn: (m: Mode) => T): Promise<T> {
  const m = mode();
  await sleep(m === 'slow' ? 2500 : 250 + Math.random() * 250);
  if (m === 'error') throw new ApiError('The request failed. Nothing has changed on your side; try again in a moment.', 503);
  return structuredClone(fn(m));
}

export const notFound = (what: string): never => {
  throw new ApiError(`${what} not found`, 404);
};

/**
 * Search, facet-filter and page rows the way a list endpoint would. `value` may return several values for a
 * multi-valued field (tags, attached knowledge bases): a row matches when any of them is selected.
 */
export function list<T>(
  rows: T[],
  p: ListParams,
  opts: { text: (r: T) => string; value: (r: T, key: string) => string | string[]; facetKeys: string[] },
  m: Mode,
): ListResult<T> {
  const all = m === 'empty' ? [] : rows;
  const q = p.search?.toLowerCase();
  const searched = q ? all.filter((r) => opts.text(r).toLowerCase().includes(q)) : all;
  const filters = Object.entries(p.filters ?? {}).filter(([, v]) => v?.length) as [string, string[]][];
  const valuesOf = (r: T, k: string) => [opts.value(r, k)].flat();
  const match = (r: T, skip?: string) => filters.every(([k, v]) => k === skip || valuesOf(r, k).some((x) => v.includes(x)));
  const filtered = searched.filter((r) => match(r));
  // Each facet counts rows under every other active filter, so its options show what selecting them would yield.
  const facets = Object.fromEntries(
    opts.facetKeys.map((k) => {
      const counts: Record<string, number> = {};
      for (const r of searched.filter((x) => match(x, k))) for (const v of valuesOf(r, k)) counts[v] = (counts[v] ?? 0) + 1;
      return [k, counts];
    }),
  );
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / p.pageSize));
  const page = Math.min(p.page, totalPages);
  return {
    data: filtered.slice((page - 1) * p.pageSize, page * p.pageSize),
    pagination: { page, pageSize: p.pageSize, total, totalPages, hasNext: page < totalPages, hasPrev: page > 1 },
    facets,
  };
}

export const field = <T,>(r: T, k: string) => String((r as Record<string, unknown>)[k]);
export const id = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 8)}`;

/** Applies fn to each id; a returned string is the reason that item was skipped. */
export function bulk(ids: string[], fn: (id: string) => string | void): BulkResult {
  const out: BulkResult = { updated: [], skipped: [] };
  for (const i of ids) {
    const reason = fn(i);
    if (reason) out.skipped.push({ id: i, reason });
    else out.updated.push(i);
  }
  return out;
}
