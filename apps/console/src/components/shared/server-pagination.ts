import type { DataTableWithViewsServerPagination } from '@/components/data-table-with-views';
import type { PaginationState } from '@/lib/types/pagination';

/**
 * A server-paged list's table paging, from its list params (useListParams) and its query: the one place every list
 * page reads total, page, page size and "loading the next page" from, instead of each page spelling them out.
 */
export function serverPagination(
  list: { pagination: PaginationState; setPagination: (p: PaginationState) => void },
  query: { data?: { pagination: { page?: number; total: number; totalPages?: number } }; isFetching: boolean; isPlaceholderData: boolean },
): DataTableWithViewsServerPagination {
  return {
    enabled: true,
    total: query.data?.pagination.total ?? 0,
    // A page past the last answers the last page with its number; show that one once it has loaded.
    page: query.isPlaceholderData ? list.pagination.page : (query.data?.pagination.page ?? list.pagination.page),
    pageSize: list.pagination.pageSize,
    totalPages: query.data?.pagination.totalPages,
    onPaginationChange: list.setPagination,
    isLoading: query.isFetching && query.isPlaceholderData,
  };
}
