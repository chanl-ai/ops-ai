import type { AllowList, EgressChange, EgressKind } from '@/lib/types/egress';

/**
 * The tenant's egress allow-list: every outbound tool request must be https to a listed host, resolving only into
 * public addresses or listed private ranges. A value that can never be listed is refused (400, naming why); a host a
 * module still calls cannot be removed (409, naming the modules).
 */
export interface EgressApi {
  list(): Promise<AllowList>;
  add(kind: EgressKind, value: string, note: string): Promise<EgressChange>;
  remove(kind: EgressKind, value: string): Promise<EgressChange>;
}
