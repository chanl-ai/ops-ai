'use client';

import * as React from 'react';
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  PaginationState as TanStackPaginationState,
} from '@tanstack/react-table';
import { LayoutGrid, Table as TableIcon } from 'lucide-react';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { DataTablePagination, ServerPaginationProps } from './data-table-pagination';
import {
  DataTableToolbar,
  type DateRangeFilter,
  type BulkAction,
  type ExternalFilter,
} from './data-table-toolbar';
import { PaginationState, PAGINATION_DEFAULTS } from '@/lib/types/pagination';
import { useBulkSelectionTransport } from '@/components/bulk-selection-context';

// Re-export ExternalFilter for backwards compatibility
export type { ExternalFilter };
/** Convert 1-based API page to 0-based table page index */
const pageToPageIndex = (page: number) => Math.max(0, page - 1);

/**
 * Server-side pagination configuration for DataTableWithViews
 */
export interface DataTableWithViewsServerPagination {
  /** Enable server-side pagination mode */
  enabled: boolean;
  /** Total number of items across all pages */
  total: number;
  /** Current page (1-indexed) */
  page: number;
  /** Number of items per page */
  pageSize: number;
  /** Total number of pages (calculated if not provided) */
  totalPages?: number;
  /** Callback when pagination changes */
  onPaginationChange: (pagination: PaginationState) => void;
  /** Whether data is currently loading */
  isLoading?: boolean;
}

interface DataTableWithViewsProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
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
  /** Initial sorting state - useful for default sort order */
  initialSorting?: SortingState;
  // Grid view props
  renderGridItem?: (item: TData) => React.ReactNode;
  /** Class for each grid item wrapper (default: "w-80"). Ignored when gridClassName is set. */
  gridItemClassName?: string;
  /** Class for the grid container (default: flex-wrap). Use CSS grid classes for responsive fill. */
  gridClassName?: string;
  defaultView?: 'table' | 'grid';
  /** Hide the table/grid view toggle button (view stays locked to defaultView) */
  hideViewSwitcher?: boolean;
  // Selection callback
  onSelectionChange?: (selectedRows: TData[]) => void;
  /** Bump this number to imperatively clear row selection (e.g. after a bulk
   *  action completes, so the selection doesn't stick to whatever rows now sit
   *  at those indices after a refetch). */
  selectionResetKey?: number;
  /** Bump to clear the search and every filter, e.g. from a filtered-empty state's Clear filters. */
  filterResetKey?: number;
  /**
   * Stable row identity. WITHOUT this TanStack keys rowSelection by array
   * INDEX, so a selection that outlives a refetch silently re-binds to whoever
   * shifted into that position — select two rows, delete them, and the
   * checkboxes land on two different records with Delete still armed. Pass the
   * record's id and a stale key simply drops instead.
   */
  getRowId?: (row: TData) => string;
  /** Custom empty state to render when data is empty and not loading */
  emptyState?: React.ReactNode;
  /** Callback when column filters change (for server-side search) */
  onColumnFiltersChange?: (filters: ColumnFiltersState) => void;
  /** Initial column filters (for URL-based filtering) */
  initialColumnFilters?: ColumnFiltersState;
  /**
   * Server-side pagination configuration.
   * When enabled, DataTableWithViews uses manual pagination instead of client-side.
   */
  serverPagination?: DataTableWithViewsServerPagination;
  /** Date range filter — renders a DateRangePicker in the toolbar */
  dateRange?: DateRangeFilter;
  /** Initial column visibility state (e.g., { toolId: false } to hide a column) */
  initialColumnVisibility?: VisibilityState;
  /** Extra content rendered at the end of the toolbar row (e.g. toggles, buttons) */
  toolbarExtra?: React.ReactNode;
  /** Custom filter controls rendered inside the filter bar, after search */
  prependFilters?: React.ReactNode;
}

export function DataTableWithViews<TData, TValue>({
  columns,
  data,
  searchColumn = 'title',
  searchPlaceholder = 'Filter...',
  filters = [],
  externalFilters = [],
  bulkActions = [],
  initialSorting = [],
  renderGridItem,
  gridItemClassName = 'w-80',
  gridClassName,
  defaultView = 'table',
  hideViewSwitcher = false,
  onSelectionChange,
  selectionResetKey,
  filterResetKey,
  onColumnFiltersChange: onColumnFiltersChangeProp,
  initialColumnFilters = [],
  emptyState,
  serverPagination,
  dateRange,
  initialColumnVisibility = {},
  toolbarExtra,
  prependFilters,
  getRowId,
}: DataTableWithViewsProps<TData, TValue>) {
  const [rowSelection, setRowSelection] = React.useState({});
  const [columnVisibility, setColumnVisibility] =
    React.useState<VisibilityState>(initialColumnVisibility);
  const [columnFilters, setColumnFilters] =
    React.useState<ColumnFiltersState>(initialColumnFilters);
  const [sorting, setSorting] = React.useState<SortingState>(initialSorting);
  const [view, setView] = React.useState<'table' | 'grid'>(defaultView);

  // For server-side pagination, we need to track pagination state
  const [clientPagination, setClientPagination] = React.useState<TanStackPaginationState>(() => ({
    pageIndex: serverPagination ? pageToPageIndex(serverPagination.page) : 0,
    pageSize: serverPagination?.pageSize ?? PAGINATION_DEFAULTS.PAGE_SIZE,
  }));

  // Sync client pagination with server pagination when it changes externally
  React.useEffect(() => {
    if (serverPagination?.enabled) {
      setClientPagination({
        pageIndex: pageToPageIndex(serverPagination.page),
        pageSize: serverPagination.pageSize,
      });
    }
  }, [serverPagination?.enabled, serverPagination?.page, serverPagination?.pageSize]);

  // Calculate total pages for server pagination
  const serverTotalPages = serverPagination?.enabled
    ? (serverPagination.totalPages ??
        Math.ceil(serverPagination.total / serverPagination.pageSize)) ||
      1
    : 0;

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      columnVisibility,
      rowSelection,
      columnFilters,
      pagination: clientPagination,
    },
    // Server-side pagination configuration
    manualPagination: serverPagination?.enabled ?? false,
    pageCount: serverPagination?.enabled ? serverTotalPages : undefined,
    enableRowSelection: true,
    ...(getRowId ? { getRowId: (row: TData) => getRowId(row) } : {}),
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setClientPagination,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    // Only use client-side pagination model when NOT using server pagination
    getPaginationRowModel: serverPagination?.enabled ? undefined : getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
  });

  // Notify parent of column filter changes (for server-side search)
  React.useEffect(() => {
    if (onColumnFiltersChangeProp) {
      onColumnFiltersChangeProp(columnFilters);
    }
  }, [columnFilters, onColumnFiltersChangeProp]);

  // Notify parent of selection changes
  React.useEffect(() => {
    if (onSelectionChange) {
      const selectedRows = table.getSelectedRowModel().rows.map((row) => row.original);
      onSelectionChange(selectedRows);
    }
  }, [rowSelection, onSelectionChange, table]);

  // Imperative selection clear — parent bumps selectionResetKey after a bulk
  // action so the checkboxes don't linger on rows that shifted under a refetch.
  const didMountResetRef = React.useRef(false);
  React.useEffect(() => {
    if (selectionResetKey === undefined) return;
    if (!didMountResetRef.current) {
      didMountResetRef.current = true;
      return; // skip the initial mount so we don't clear a pre-seeded selection
    }
    table.resetRowSelection();
  }, [selectionResetKey, table]);

  const didMountFilterResetRef = React.useRef(false);
  React.useEffect(() => {
    if (filterResetKey === undefined) return;
    if (!didMountFilterResetRef.current) {
      didMountFilterResetRef.current = true;
      return;
    }
    table.resetColumnFilters();
  }, [filterResetKey, table]);

  // Transport bulk actions to PageLayout header when inside a PageLayout
  const bulkTransport = useBulkSelectionTransport();
  const rowSelectionKeys = Object.keys(rowSelection).filter(
    (k) => (rowSelection as Record<string, boolean>)[k]
  );
  const transportActive = !!bulkTransport && bulkActions.length > 0;

  React.useEffect(() => {
    if (!transportActive) return;
    if (!bulkTransport) return;

    const selected = table.getFilteredSelectedRowModel().rows.map((r) => r.original);
    if (selected.length > 0) {
      bulkTransport.register({
        count: selected.length,
        actions: bulkActions.map((action) => ({
          label: action.label,
          icon: action.icon,
          variant: action.variant,
          onClick: () => action.onClick(selected),
        })),
        onClear: () => table.resetRowSelection(),
      });
    } else {
      bulkTransport.unregister();
    }

    return () => bulkTransport.unregister();
    // `data` is a dep because the registered payload closes over rows resolved
    // from it. A refetch that drops or reorders selected rows leaves the same
    // selection keys, so without this the header keeps the pre-refetch count and
    // the action fires against row objects that are no longer in the table.
  }, [transportActive, rowSelectionKeys.join(','), bulkActions, data]);

  // Build server pagination props for DataTablePagination
  const serverPaginationProps: ServerPaginationProps | undefined = serverPagination?.enabled
    ? {
        total: serverPagination.total,
        totalPages: serverTotalPages,
        page: serverPagination.page,
        pageSize: serverPagination.pageSize,
        onPageChange: (page: number) => {
          serverPagination.onPaginationChange({
            page,
            pageSize: serverPagination.pageSize,
          });
        },
        onPageSizeChange: (pageSize: number) => {
          serverPagination.onPaginationChange({
            page: 1, // Reset to first page when changing page size
            pageSize,
          });
        },
      }
    : undefined;

  return (
    <div className="space-y-4 py-4" data-testid="data-table-container">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {renderGridItem && !hideViewSwitcher && (
          <div
            className="flex items-center gap-1 border rounded-md shrink-0 bg-card"
            data-testid="view-toggle"
          >
            <Button
              variant={view === 'table' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setView('table')}
              className="h-8 px-3"
              data-testid="view-toggle-table"
            >
              <TableIcon className="h-4 w-4" />
            </Button>
            <Button
              variant={view === 'grid' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setView('grid')}
              className="h-8 px-3"
              data-testid="view-toggle-grid"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <DataTableToolbar
            table={table}
            searchColumn={searchColumn}
            searchPlaceholder={searchPlaceholder}
            filters={filters}
            externalFilters={externalFilters}
            bulkActions={transportActive ? [] : bulkActions}
            dateRange={dateRange}
            prependFilters={prependFilters}
          />
        </div>
        {toolbarExtra}
      </div>

      {view === 'table' ? (
        <div
          className="rounded-md border bg-card flex flex-col overflow-hidden"
          data-testid="table-view"
        >
          <div className="flex-1 min-h-0">
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-background">
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      return (
                        <TableHead key={header.id} colSpan={header.colSpan} className={(header.column.columnDef.meta as { className?: string } | undefined)?.className}>
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                        </TableHead>
                      );
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {serverPagination?.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="h-24 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        Loading...
                      </div>
                    </TableCell>
                  </TableRow>
                ) : table.getRowModel().rows?.length ? (
                  table.getRowModel().rows.map((row) => {
                    const rowData = row.original as any;
                    return (
                      <TableRow
                        key={row.id}
                        data-state={row.getIsSelected() && 'selected'}
                        data-testid={rowData?.rowTestId}
                        className={rowData?.onRowClick ? 'cursor-pointer' : undefined}
                        onClick={(e) => {
                          // Rows that have an address open it in a new tab on cmd/ctrl-click, like a link would.
                          if (rowData?.href && (e.metaKey || e.ctrlKey)) {
                            window.open(rowData.href, '_blank', 'noopener');
                            return;
                          }
                          if (rowData?.onRowClick) {
                            rowData.onRowClick(row.original);
                          }
                        }}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id} className={(cell.column.columnDef.meta as { className?: string } | undefined)?.className}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    );
                  })
                ) : emptyState ? (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="p-0 border-0 whitespace-normal">
                      {emptyState}
                    </TableCell>
                  </TableRow>
                ) : (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="h-24 text-center">
                      No results.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      ) : (
        <div className="min-h-[400px]" data-testid="grid-view">
          {table.getRowModel().rows?.length ? (
            <div className={gridClassName || 'flex flex-wrap items-stretch gap-4'}>
              {table.getRowModel().rows.map((row) => (
                <div
                  key={row.id}
                  className={gridClassName ? undefined : gridItemClassName}
                  data-testid={`grid-item-${row.id}`}
                >
                  {renderGridItem?.(row.original)}
                </div>
              ))}
            </div>
          ) : emptyState ? (
            <div>{emptyState}</div>
          ) : (
            <div className="flex items-center justify-center h-64 text-center">
              <div>
                <p className="text-muted-foreground">No results found.</p>
                <p className="text-sm text-muted-foreground">Try adjusting your filters.</p>
              </div>
            </div>
          )}
        </div>
      )}

      <DataTablePagination table={table} serverPagination={serverPaginationProps} />
    </div>
  );
}
