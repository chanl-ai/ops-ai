import type { CatalogModel, ProviderConnection, ProviderConnectionInput, ProviderTypeInfo } from '@/lib/types/models';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * The account's model provider connections on models-service (`/v1/models/providers`): account admins
 * (settings.manage, held in the Security team) list and add them; a connection names its key, never holds it.
 */
export interface ProviderConnectionsApi {
  /** 403 `admin_only` for anyone else. */
  list(p: ListParams): Promise<ListResult<ProviderConnection>>;
  /** 400 naming the field the type refuses; 409 `provider_exists` for a name in use. */
  create(input: ProviderConnectionInput): Promise<{ id: string; name: string; type: string }>;
  /** The provider types a connection can be made of, each with its fields as a JSON Schema (`x-secret` fields are saved sealed). */
  types(): Promise<ProviderTypeInfo[]>;
  /** The catalog's models for a connection (capabilities, context, price); empty for a type the catalog does not hold. */
  catalog(providerId: string): Promise<CatalogModel[]>;
}
