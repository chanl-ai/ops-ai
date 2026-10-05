'use client';

import * as React from 'react';
import { useState, useMemo } from 'react';
import { X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DataTableFacetedFilter } from '@/components/data-table-faceted-filter';
import {
  ColumnFiltersState,
  getCoreRowModel,
  getFilteredRowModel,
  useReactTable,
  createColumnHelper,
} from '@tanstack/react-table';
/** Minimal Agent type for search/filter (inlined from legacy @/lib/api/types) */
interface Agent {
  id: string;
  name: string;
  status: string;
  platform: string;
  [key: string]: unknown;
}

/** Minimal Scorecard type for search/filter (inlined from legacy @/lib/api/types) */
interface Scorecard {
  id: string;
  name: string;
  status?: string;
  [key: string]: unknown;
}

export interface SearchAndFilterProps<TData> {
  data: TData[];
  searchColumn: keyof TData;
  searchPlaceholder?: string;
  filters?: {
    column: keyof TData;
    title: string;
    options: {
      label: string;
      value: string;
      icon?: React.ComponentType<{ className?: string }>;
    }[];
  }[];
  onFilteredDataChange?: (filteredData: TData[]) => void;
}

/**
 * Reusable SearchAndFilter component for card grids.
 * Uses TanStack Table for filtering logic (same as DataTableToolbar).
 */
export function SearchAndFilter<TData extends object>({
  data,
  searchColumn,
  searchPlaceholder = 'Search...',
  filters = [],
  onFilteredDataChange,
}: SearchAndFilterProps<TData>) {
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState('');

  // Create a minimal table instance for filtering
  const columnHelper = createColumnHelper<TData>();
  const columns = useMemo(
    () => [
      // TanStack Table's type system doesn't easily accept dynamic keys
      // Using accessor function form for better type safety than 'as any'
      columnHelper.accessor((row: TData) => row[searchColumn] as unknown, {
        id: String(searchColumn),
      }),
      ...filters.map((filter) =>
        columnHelper.accessor((row: TData) => row[filter.column] as unknown, {
          id: String(filter.column),
        })
      ),
    ],
    [searchColumn, filters, columnHelper]
  );

  const table = useReactTable({
    data,
    columns,
    state: {
      columnFilters,
    },
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: 'includesString',
  });

  // Handle search separately (not using globalFilter)
  const searchColumnRef = React.useRef(table.getColumn(String(searchColumn)));
  React.useEffect(() => {
    searchColumnRef.current = table.getColumn(String(searchColumn));
  }, [table, searchColumn]);

  React.useEffect(() => {
    if (searchColumnRef.current) {
      searchColumnRef.current.setFilterValue(globalFilter || undefined);
    }
  }, [globalFilter]);

  // Notify parent of filtered data changes
  // Memoize filtered rows to prevent infinite re-renders
  const filteredRows = useMemo(
    () => table.getFilteredRowModel().rows,
    [data, columnFilters, globalFilter]
  );

  // Use a ref to always call the latest onFilteredDataChange
  const callbackRef = React.useRef(onFilteredDataChange);
  React.useEffect(() => {
    callbackRef.current = onFilteredDataChange;
  }, [onFilteredDataChange]);

  // Only trigger callback when actual filter values change
  React.useEffect(() => {
    if (callbackRef.current) {
      callbackRef.current(filteredRows.map((r) => r.original));
    }
  }, [filteredRows]);

  const isFiltered = columnFilters.length > 0 || (globalFilter && globalFilter.length > 0);

  return (
    <div className="flex items-center justify-between mb-4">
      <div className="flex flex-1 items-center space-x-2">
        <Input
          placeholder={searchPlaceholder}
          value={globalFilter}
          onChange={(event) => setGlobalFilter(event.target.value)}
          className="h-8 w-[150px] lg:w-[250px]"
          data-testid="card-grid-search"
        />
        {filters.map((filter) => {
          const column = table.getColumn(String(filter.column));
          return column ? (
            <DataTableFacetedFilter
              key={String(filter.column)}
              column={column}
              title={filter.title}
              options={filter.options}
            />
          ) : null;
        })}
        {isFiltered && (
          <Button
            variant="ghost"
            onClick={() => {
              setColumnFilters([]);
              setGlobalFilter('');
            }}
            className="h-8 px-2 lg:px-3"
            data-testid="card-grid-reset-filters"
          >
            Reset
            <X className="ml-2 h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

// Type-safe SearchAndFilter props for specific resource types
export type SearchAndFilterForAgent = SearchAndFilterProps<Agent>;
export type SearchAndFilterForScorecard = SearchAndFilterProps<Scorecard>;
