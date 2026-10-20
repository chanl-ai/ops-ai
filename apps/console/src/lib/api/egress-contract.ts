import type { AllowList, EgressChange, EgressKind, ListedHost } from '@/lib/types/egress';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * The tenant's egress allow-list: every outbound tool request must be https to a listed host, resolving only into
 * public addresses or listed private ranges. A value that can never be listed is refused (400, naming why); a host a
 * module still calls cannot be removed (409, naming the modules).
 */
export interface EgressApi {
  list(): Promise<AllowList>;
  /** One page of the listed hosts whose name or note matches the search, by name. */
  hosts(p: ListParams): Promise<ListResult<ListedHost>>;
  add(kind: EgressKind, value: string, note: string): Promise<EgressChange>;
  remove(kind: EgressKind, value: string): Promise<EgressChange>;
}
