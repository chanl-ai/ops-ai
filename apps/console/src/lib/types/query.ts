import type { FacetCounts } from './domain';
import type { PaginationMeta } from './pagination';

export interface ListParams<F extends Record<string, string[] | undefined> = Record<string, string[] | undefined>> {
  page: number;
  pageSize: number;
  search?: string;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  filters?: F;
}

export interface ListResult<T> {
  data: T[];
  pagination: PaginationMeta;
  facets: FacetCounts;
}

/** One choice in an EntityPicker; `disabled` says why it cannot be chosen. */
export interface Option {
  id: string;
  label: string;
  hint?: string | null;
  disabled?: string | null;
}

/** A page of picker choices from an `/options` route; `nextCursor` is null at the end. */
export interface OptionsPage {
  data: Option[];
  nextCursor: string | null;
}

/** What every `/options` route takes: a search, the cursor of the page, a limit, or the stored ids to label. */
export interface OptionsParams {
  search?: string;
  cursor?: string | null;
  limit?: number;
  ids?: string[];
}

export type ReviewView = 'mine' | 'open' | 'overdue' | 'resolved' | 'all';

export type ReviewFilters = { risk?: string[]; workflowId?: string[]; kind?: string[]; agentSlug?: string[]; status?: string[] };
export type ReviewListParams = ListParams<ReviewFilters> & { view: ReviewView };

export type AgentFilters = { availability?: string[]; teamId?: string[] };
export type WorkflowFilters = { status?: string[] };
export type PolicyFilters = { workflowId?: string[] };
export type RunFilters = { status?: string[] };
export type DeploymentFilters = { channel?: string[]; environment?: string[]; workflowId?: string[]; status?: string[] };
export type ToolFilters = { access?: string[]; type?: string[]; system?: string[] };

export interface ReviewViewCounts {
  mine: number;
  open: number;
  overdue: number;
  resolved: number;
}

export interface ReviewStats {
  unassigned: number;
  medianDecisionMinutes: number;
  medianDecisionTrendMinutes: number;
  approvedAsProposedRate: number;
  decidedToday: number;
}

export interface ToolStats {
  total: number;
  disabled: number;
  systems: number;
  calls24h: number;
  callsTrendPct: number;
  busiest: string;
  requireReview: number;
  noisy: string[];
}
