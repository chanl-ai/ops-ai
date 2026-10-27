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
  /** Saved in the current team, the only team whose tool modules read it. */
  create(name: string, value: string): Promise<SecretMeta>;
  rotate(name: string, value: string): Promise<SecretMeta>;
  /** Refused with 409 `secret_in_use` while an operation names it. */
  remove(name: string): Promise<void>;
}
