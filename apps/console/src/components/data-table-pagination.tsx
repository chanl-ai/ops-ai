import { Table } from '@tanstack/react-table';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PAGINATION_DEFAULTS } from '@/lib/types/pagination';

/**
 * Server-side pagination props for when data is paginated on the server
 */
export interface ServerPaginationProps {
  /** Total number of items across all pages */
  total: number;
  /** Total number of pages */
  totalPages: number;
  /** Current page (1-indexed) */
  page: number;
  /** Number of items per page */
  pageSize: number;
  /** Callback when page changes */
  onPageChange: (page: number) => void;
  /** Callback when page size changes */
  onPageSizeChange: (pageSize: number) => void;
}

interface DataTablePaginationProps<TData> {
  table: Table<TData>;
  /**
   * Server-side pagination props. When provided, the component uses these values
   * instead of the TanStack table's built-in pagination.
   */
  serverPagination?: ServerPaginationProps;
}

export function DataTablePagination<TData>({
  table,
  serverPagination,
}: DataTablePaginationProps<TData>) {
  // Determine if we're using server or client pagination
  const isServerPagination = !!serverPagination;

  // Get pagination values from either server props or table state
  const currentPage = isServerPagination
    ? serverPagination.page
    : table.getState().pagination.pageIndex + 1; // Convert 0-indexed to 1-indexed

  const pageSize = isServerPagination
    ? serverPagination.pageSize
    : table.getState().pagination.pageSize;

  const totalPages = isServerPagination ? serverPagination.totalPages : table.getPageCount();

  const totalRows = isServerPagination
    ? serverPagination.total
    : table.getFilteredRowModel().rows.length;

  const selectedRows = table.getFilteredSelectedRowModel().rows.length;

  // Navigation handlers
  const canGoPrevious = isServerPagination ? currentPage > 1 : table.getCanPreviousPage();

  const canGoNext = isServerPagination ? currentPage < totalPages : table.getCanNextPage();

  const handleFirstPage = () => {
    if (isServerPagination) {
      serverPagination.onPageChange(1);
    } else {
      table.setPageIndex(0);
    }
  };

  const handlePreviousPage = () => {
    if (isServerPagination) {
      serverPagination.onPageChange(currentPage - 1);
    } else {
      table.previousPage();
    }
  };

  const handleNextPage = () => {
    if (isServerPagination) {
      serverPagination.onPageChange(currentPage + 1);
    } else {
      table.nextPage();
    }
  };

  const handleLastPage = () => {
    if (isServerPagination) {
      serverPagination.onPageChange(totalPages);
    } else {
      table.setPageIndex(table.getPageCount() - 1);
    }
  };

  const handlePageSizeChange = (value: string) => {
    const newSize = Number(value);
    if (isServerPagination) {
      serverPagination.onPageSizeChange(newSize);
    } else {
      table.setPageSize(newSize);
    }
  };

  return (
    <div className="flex items-center justify-between px-2">
      <div className="flex-1 text-sm text-muted-foreground">
        {selectedRows > 0 ? (
          <>
            {selectedRows} of {totalRows} selected
          </>
        ) : (
          <>{totalRows === 1 ? '1 row' : `${totalRows} rows`}</>
        )}
      </div>
      <div className="flex items-center space-x-6 lg:space-x-8">
        <div className="flex items-center space-x-2">
          <p className="text-sm font-medium">Rows per page</p>
          <Select value={`${pageSize}`} onValueChange={handlePageSizeChange}>
            <SelectTrigger className="h-8 w-[70px]">
              <SelectValue placeholder={pageSize} />
            </SelectTrigger>
            <SelectContent side="top">
              {PAGINATION_DEFAULTS.PAGE_SIZE_OPTIONS.map((size) => (
                <SelectItem key={size} value={`${size}`}>
                  {size}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-[100px] items-center justify-center text-sm font-medium">
          Page {currentPage} of {totalPages || 1}
        </div>
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            className="hidden h-8 w-8 p-0 lg:flex"
            onClick={handleFirstPage}
            disabled={!canGoPrevious}
          >
            <span className="sr-only">Go to first page</span>
            <ChevronsLeft />
          </Button>
          <Button
            variant="outline"
            className="h-8 w-8 p-0"
            onClick={handlePreviousPage}
            disabled={!canGoPrevious}
          >
            <span className="sr-only">Go to previous page</span>
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            className="h-8 w-8 p-0"
            onClick={handleNextPage}
            disabled={!canGoNext}
          >
            <span className="sr-only">Go to next page</span>
            <ChevronRight />
          </Button>
          <Button
            variant="outline"
            className="hidden h-8 w-8 p-0 lg:flex"
            onClick={handleLastPage}
            disabled={!canGoNext}
          >
            <span className="sr-only">Go to last page</span>
            <ChevronsRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
