import type { ListParams, ListResult } from '@/lib/types/query';
import type { SecretMeta } from '@/lib/types/secrets';

/**
 * Credentials tool calls send, kept encrypted by tools-service and never returned. A name is upper snake case
 * (`STATEMENTS_KEY`); creating a taken name is refused (409) and points at rotate; a rotation reaches the next call.
 */
export interface SecretsApi {
  list(): Promise<SecretMeta[]>;
  /** One page of the secrets whose name matches the search, by name. */
  page(p: ListParams): Promise<ListResult<SecretMeta>>;
  /** `teams` limits which teams' tool modules may read it; left out, every team. */
  create(name: string, value: string, teams?: string[] | null): Promise<SecretMeta>;
  rotate(name: string, value: string): Promise<SecretMeta>;
  /** Security admins: the teams whose modules may read it; null is every team. */
  setScope(name: string, teams: string[] | null): Promise<SecretMeta>;
  /** Refused with 409 `secret_in_use` while an operation names it. */
  remove(name: string): Promise<void>;
}
