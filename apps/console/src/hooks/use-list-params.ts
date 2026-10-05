'use client';

import * as React from 'react';
import type { ColumnFiltersState } from '@tanstack/react-table';

import { type PaginationState, PAGINATION_DEFAULTS } from '@/lib/types/pagination';
import type { ListParams } from '@/lib/types/query';

/**
 * Bridges DataTableWithViews (column filter state, 1-based pagination) to API list params.
 * The search column's text becomes `search`; every other column filter becomes a facet filter.
 * Any filter change returns to page 1 so the user never lands on an empty page.
 */
export function useListParams<F extends Record<string, string[] | undefined>>(searchColumn?: string, pageSize: number = PAGINATION_DEFAULTS.PAGE_SIZE) {
  const [pagination, setPagination] = React.useState<PaginationState>({ page: 1, pageSize });
  const [search, setSearch] = React.useState('');
  const [debouncedSearch, setDebouncedSearch] = React.useState('');
  const [filters, setFilters] = React.useState<F>({} as F);

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
  }, [debouncedSearch, filters]);

  const params: ListParams<F> = {
    page: pagination.page,
    pageSize: pagination.pageSize,
    search: debouncedSearch || undefined,
    filters,
  };

  const reset = React.useCallback(() => setPagination((p) => ({ ...p, page: 1 })), []);

  return { params, pagination, setPagination, onColumnFiltersChange, reset, isFiltered: !!debouncedSearch || Object.keys(filters).length > 0 };
}

/** Column filterFn for faceted multi-select filters (the table re-applies server filters to the page it holds). */
export const facetFilterFn = (row: { getValue: (id: string) => unknown }, id: string, value: string[]) =>
  !value?.length || value.includes(String(row.getValue(id)));

