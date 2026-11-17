'use client';

import * as React from 'react';
import type { ColumnFiltersState, SortingState } from '@tanstack/react-table';

import { hasEveryWord } from '@/lib/search-words';
import { type PaginationState, PAGINATION_DEFAULTS } from '@/lib/types/pagination';
import type { ListParams } from '@/lib/types/query';

/**
 * Bridges DataTableWithViews (column filter state, 1-based pagination) to API list params.
 * The search column's text becomes `search`; every other column filter becomes a facet filter.
 * Any filter change returns to page 1 so the user never lands on an empty page. `sortColumns` maps a table column to the
 * API's `sortBy` value; the table passes `serverSort` to `serverSorting`, so a header click asks the server for the
 * order of the whole list and returns to page 1.
 */
export function useListParams<F extends Record<string, string[] | undefined>>(
  searchColumn?: string,
  pageSize: number = PAGINATION_DEFAULTS.PAGE_SIZE,
  initialFilters?: F,
  sortColumns?: Record<string, string>,
) {
  const [pagination, setPagination] = React.useState<PaginationState>({ page: 1, pageSize });
  const [search, setSearch] = React.useState('');
  const [debouncedSearch, setDebouncedSearch] = React.useState('');
  // A page linked with its filters in the URL (`/govern/activity?kind=email`) asks for them on its first read; pass the same
  // filters to the table as `initialColumnFilters` so its facets show them chosen.
  const [filters, setFilters] = React.useState<F>(initialFilters ?? ({} as F));
  const [sort, setSort] = React.useState<{ sortBy: string; sortOrder: 'asc' | 'desc' } | undefined>();

  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const onColumnFiltersChange = React.useCallback(
    (state: ColumnFiltersState) => {
      const nextSearch = (state.find((f) => f.id === searchColumn)?.value as string | undefined) ?? '';
      const nextFilters = Object.fromEntries(
        state.filter((f) => f.id !== searchColumn && Array.isArray(f.value) && f.value.length).map((f) => [f.id, f.value as string[]]),
      ) as F;
      setSearch((prev) => (prev === nextSearch ? prev : nextSearch));
      setFilters((prev) => (JSON.stringify(prev) === JSON.stringify(nextFilters) ? prev : nextFilters));
    },
    [searchColumn],
  );

  React.useEffect(() => {
    setPagination((p) => (p.page === 1 ? p : { ...p, page: 1 }));
  }, [debouncedSearch, filters, sort]);

  const params: ListParams<F> = {
    page: pagination.page,
    pageSize: pagination.pageSize,
    search: debouncedSearch || undefined,
    ...sort,
    filters,
  };

  const serverSort = React.useMemo(
    () =>
      sortColumns
        ? {
            columns: Object.keys(sortColumns),
            onChange: (state: SortingState) => {
              const first = state[0];
              const by = first ? sortColumns[first.id] : undefined;
              setSort(by ? { sortBy: by, sortOrder: first.desc ? ('desc' as const) : ('asc' as const) } : undefined);
            },
          }
        : undefined,
    [sortColumns],
  );

  const reset = React.useCallback(() => setPagination((p) => ({ ...p, page: 1 })), []);

  return { params, pagination, setPagination, onColumnFiltersChange, reset, serverSort, isFiltered: !!debouncedSearch || Object.keys(filters).length > 0 };
}

/** Filters as the table's column filter state, for `initialColumnFilters`. */
export const columnFiltersOf = (filters: Record<string, string[] | undefined>): ColumnFiltersState =>
  Object.entries(filters)
    .filter(([, v]) => v?.length)
    .map(([id, value]) => ({ id, value }));

/** Column filterFn for faceted multi-select filters (the table re-applies server filters to the page it holds). */
export const facetFilterFn = (row: { getValue: (id: string) => unknown }, id: string, value: string[]) =>
  !value?.length || value.includes(String(row.getValue(id)));

/**
 * Column filterFn for a list the server searches: the page it returns is filtered again on the same rule, every word in
 * any of `fields`, so the table never hides a row the server matched.
 */
export const wordsFilterFn =
  <T extends object>(fields: (keyof T)[]) =>
  (row: { original: T }, _id: string, value: string) =>
    !value || hasEveryWord(fields.map((f) => row.original[f] as string | null | undefined), value);
