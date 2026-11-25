import type { ModelAliasInput, ModelAliasRow } from '@/lib/types/models';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * The account's model aliases on models-service (`/v1/models/aliases`): account admins list and make them. An alias
 * is versioned, never edited: repointing it saves a new version, and agents on the name pick it up.
 */
export interface ModelAliasesApi {
  /** The newest version of each alias; 403 `admin_only` for anyone else. */
  list(p: ListParams): Promise<ListResult<ModelAliasRow>>;
  /** 409 `alias_exists` for a name in use; 400 for a connection or model it does not know. */
  create(input: ModelAliasInput & { name: string }): Promise<{ name: string; version: number }>;
  /** A new version under the same name. */
  newVersion(name: string, input: ModelAliasInput): Promise<{ name: string; version: number }>;
}
