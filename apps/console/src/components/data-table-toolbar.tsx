'use client';

import { Table } from '@tanstack/react-table';
import { X } from 'lucide-react';
import Link from 'next/link';

import { type DateRange } from 'react-day-picker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { DataTableViewOptions } from './data-table-view-options';
import { DataTableFacetedFilter } from './data-table-faceted-filter';
import { DateRangePicker } from './shared/date-range-picker';
/** External filter for URL-based or API-level filtering. */
export interface ExternalFilter {
  /** Unique identifier for the filter */
  id: string;
  /** Display label (e.g., "Execution", "Scenario") */
  label: string;
  /** Badge content to display (e.g., "#0ed509") */
  value: string;
  /** Called when the X button is clicked to clear this filter */
  onClear: () => void;
  /** Optional: clicking the badge navigates to this URL */
  href?: string;
}

/** Date range filter configuration */
export interface DateRangeFilter {
  value: DateRange | undefined;
  onChange: (range: DateRange | undefined) => void;
  placeholder?: string;
}

/** Bulk action configuration */
export interface BulkAction<TData> {
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  onClick: (selectedRows: TData[]) => void;
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
}

interface DataTableToolbarProps<TData> {
  table: Table<TData>;
  searchColumn?: string;
  searchPlaceholder?: string;
  filters?: {
    column: string;
    title: string;
    options: {
      label: string;
      value: string;
      icon?: React.ComponentType<{ className?: string }>;
      /** Server-side count of records carrying this value. */
      count?: number;
    }[];
    /** Force the search box on/off; defaults to a size heuristic. */
    searchable?: boolean;
  }[];
  /** External filters for URL-based or API-level filtering */
  externalFilters?: ExternalFilter[];
  /** Bulk actions shown when rows are selected */
  bulkActions?: BulkAction<TData>[];
  /** Date range filter — renders a DateRangePicker in the toolbar */
  dateRange?: DateRangeFilter;
  /** Custom filter controls rendered at the start of the filter bar (after search) */
  prependFilters?: React.ReactNode;
}

export function DataTableToolbar<TData>({
  table,
  searchColumn = 'title',
  searchPlaceholder = 'Filter...',
  filters = [],
  externalFilters = [],
  bulkActions = [],
  dateRange,
  prependFilters,
}: DataTableToolbarProps<TData>) {
  const hasExternalFilters = externalFilters.length > 0;
  const hasDateRange = !!dateRange?.value?.from;
  const isFiltered =
    table.getState().columnFilters.length > 0 || hasExternalFilters || hasDateRange;

  // Get selected rows for bulk actions
  const selectedRows = table.getFilteredSelectedRowModel().rows;
  const hasSelection = selectedRows.length > 0;
  const hasBulkActions = bulkActions.length > 0;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        {/* Bulk actions section - shown when rows are selected */}
        {hasBulkActions && hasSelection && (
          <>
            <Badge
              variant="secondary"
              className="h-8 px-3 rounded-md font-normal"
              data-testid="selected-count-badge"
            >
              {selectedRows.length} selected
            </Badge>
            {bulkActions.map((action, index) => {
              const Icon = action.icon;
              return (
                <Button
                  key={index}
                  variant={action.variant || 'outline'}
                  size="sm"
                  className="h-8"
                  onClick={() => action.onClick(selectedRows.map((row) => row.original))}
                  data-testid={`bulk-action-${action.label.toLowerCase().replace(/\s+/g, '-')}`}
                >
                  {Icon && <Icon className="mr-2 h-4 w-4" />}
                  {action.label}
                </Button>
              );
            })}
            <Button
              variant="ghost"
              size="sm"
              className="h-8"
              onClick={() => table.resetRowSelection()}
              data-testid="clear-selection-button"
            >
              Clear
              <X className="ml-1 h-4 w-4" />
            </Button>
            <Separator orientation="vertical" className="h-6" />
          </>
        )}
        {/* Search only when the table has the column; getColumn logs an error for a missing id. */}
        {table.getAllLeafColumns().some((c) => c.id === searchColumn) && (
          <Input
            placeholder={searchPlaceholder}
            value={(table.getColumn(searchColumn)?.getFilterValue() as string) ?? ''}
            onChange={(event) => table.getColumn(searchColumn)?.setFilterValue(event.target.value)}
            className="h-8 w-[140px] lg:w-[190px] focus:w-[240px] lg:focus:w-[300px] transition-all bg-card"
            data-testid="data-table-search"
          />
        )}
        {/* Leading custom filters (e.g. segmented type filter) */}
        {prependFilters}
        {/* Column filters (client-side TanStack filtering) */}
        {filters.map((filter) => {
          const column = table.getColumn(filter.column);
          return column ? (
            <DataTableFacetedFilter
              key={filter.column}
              column={column}
              title={filter.title}
              options={filter.options}
              searchable={filter.searchable}
            />
          ) : null;
        })}
        {/* Date range filter */}
        {dateRange && (
          <DateRangePicker
            value={dateRange.value}
            onChange={dateRange.onChange}
            placeholder={dateRange.placeholder}
          />
        )}
        {/* External filters (URL-based) - rendered after column filters, before Reset */}
        {externalFilters.map((filter) =>
          filter.href ? (
            <Button
              key={filter.id}
              variant="outline"
              size="sm"
              className="h-8 border-dashed"
              asChild
            >
              <Link href={filter.href}>
                {filter.label}
                <Badge variant="secondary" className="ml-2 rounded-sm px-1 font-normal">
                  {filter.value}
                </Badge>
              </Link>
            </Button>
          ) : (
            <Button key={filter.id} variant="outline" size="sm" className="h-8 border-dashed">
              {filter.label}
              <Badge variant="secondary" className="ml-2 rounded-sm px-1 font-normal">
                {filter.value}
              </Badge>
            </Button>
          )
        )}
        {isFiltered && (
          <Button
            variant="ghost"
            onClick={() => {
              table.resetColumnFilters();
              externalFilters.forEach((f) => f.onClear());
              dateRange?.onChange(undefined);
            }}
            className="h-8 px-2 lg:px-3"
            data-testid="reset-all-filters"
          >
            Reset
            <X />
          </Button>
        )}
      </div>
      <DataTableViewOptions table={table} />
    </div>
  );
}
