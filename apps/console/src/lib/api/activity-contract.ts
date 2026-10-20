import type { ActivityFilters, ActivityRow } from '@/lib/types/activity';
import type { ListResult } from '@/lib/types/query';

/** The workspace's activity on agents-service (`/v1/activity`); newest first, filtered and counted on the server. */
export interface ActivityApi {
  /** `facets.kind` counts ignore the kind filter and `facets.status` the status filter, so a count is one call. */
  list(params: { page: number; pageSize: number } & ActivityFilters): Promise<ListResult<ActivityRow>>;
}
