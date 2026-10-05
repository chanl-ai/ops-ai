
// ============================================================================
// PAGINATION TYPES AND CONSTANTS
// Standardized pagination infrastructure for consistent DataTable behavior
// ============================================================================

/**
 * Pagination state used by usePagination hook and DataTable components
 * Uses 1-indexed page numbers for display consistency
 */
export interface PaginationState {
  page: number; // 1-indexed for display
  pageSize: number;
}

/**
 * Pagination parameters sent to API
 * Frontend always uses page/limit, adapter converts for offset-based APIs
 */
export interface PaginationParams {
  page: number;
  limit: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
}

/**
 * Standardized pagination metadata returned from API
 */
export interface PaginationMeta {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  hasNext: boolean;
  hasPrev: boolean;
}

/**
 * Generic paginated result wrapper
 * All paginated hooks should return this format
 */
export interface PaginatedResult<T> {
  data: T[];
  pagination: PaginationMeta;
}

/**
 * Props for server-side pagination in DataTable
 */
export interface ServerPaginationProps {
  enabled: boolean;
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  onPaginationChange: (pagination: PaginationState) => void;
  isLoading?: boolean;
}

/**
 * API pagination style - determines how params are sent to backend
 */
export type ApiPaginationStyle = 'offset' | 'page';

// ============================================================================
// CONSTANTS
// ============================================================================

export const PAGINATION_DEFAULTS = {
  /** Default number of rows per page */
  PAGE_SIZE: 10,

  /** Available page size options */
  PAGE_SIZE_OPTIONS: [10, 20, 30, 50, 100] as const,

  /** Prefix for localStorage keys */
  STORAGE_KEY_PREFIX: 'ops-ai-pagination-',

  /** Default page (1-indexed) */
  DEFAULT_PAGE: 1,
} as const;

/**
 * Storage keys for different entity tables
 */
export const PAGINATION_STORAGE_KEYS = {
  scenarios: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}scenarios`,
  personas: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}personas`,
  agents: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}agents`,
  scorecards: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}scorecards`,
  calls: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}calls`,
  prompts: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}prompts`,
  executions: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}executions`,
  triggers: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}triggers`,
  knowledge: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}knowledge`,
  secrets: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}secrets`,
  tools: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}tools`,
  customers: `${PAGINATION_DEFAULTS.STORAGE_KEY_PREFIX}customers`,
} as const;

/**
 * API pagination style per entity
 * Maps entity name to the backend's expected parameter style
 */
export const ENTITY_API_STYLES: Record<string, ApiPaginationStyle> = {
  scenarios: 'offset',
  personas: 'offset',
  agents: 'offset',
  scorecards: 'offset',
  calls: 'page',
  prompts: 'offset',
  executions: 'offset',
  triggers: 'offset',
  secrets: 'offset',
} as const;

// ============================================================================
// UTILITY TYPES
// ============================================================================

/**
 * Helper type to extract page size options as a union type
 */
export type PageSizeOption = (typeof PAGINATION_DEFAULTS.PAGE_SIZE_OPTIONS)[number];

/**
 * Props required by usePagination hook
 */
export interface UsePaginationOptions {
  /** Default page size (defaults to PAGINATION_DEFAULTS.PAGE_SIZE) */
  defaultPageSize?: number;
  /** LocalStorage key for persisting page size preference */
  storageKey?: string;
  /** Whether to sync pagination state to URL params */
  syncToUrl?: boolean;
  /** Initial page (defaults to 1) */
  initialPage?: number;
}

/**
 * Return type of usePagination hook
 */
export interface UsePaginationReturn {
  /** Current pagination state */
  state: PaginationState;
  /** Current page (1-indexed) */
  page: number;
  /** Current page size */
  pageSize: number;
  /** Set page number */
  setPage: (page: number) => void;
  /** Set page size */
  setPageSize: (size: number) => void;
  /** Reset to first page */
  resetPage: () => void;
  /** Handle combined pagination change (for DataTable) */
  onChange: (pagination: PaginationState) => void;
  /** Convert to API params based on style */
  toApiParams: (style?: ApiPaginationStyle) => { offset?: number; limit: number; page?: number };
}
