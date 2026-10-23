import type { ActivityFilters, ActivityRow, BackgroundView } from '@/lib/types/activity';
import type { ListResult } from '@/lib/types/query';

/** The workspace's activity on agents-service (`/v1/activity`); newest first, filtered and counted on the server. */
export interface ActivityApi {
  /** `facets.kind` counts ignore the kind filter and `facets.status` the status filter, so a count is one call. */
  list(params: { page: number; pageSize: number } & ActivityFilters): Promise<ListResult<ActivityRow>>;
  /** Every background process with its heartbeat and the latest jobs, for account admins (`/v1/background`); 404 for anyone else. */
  background(): Promise<BackgroundView>;
}
