import type { ProviderConnection, ProviderConnectionInput } from '@/lib/types/models';

/**
 * The account's model provider connections on models-service (`/v1/models/providers`, c-605): account admins
 * (settings.manage, held in the Security team) list and add them; a connection names its key, never holds it.
 */
export interface ProviderConnectionsApi {
  /** 403 `admin_only` for anyone else. */
  list(): Promise<ProviderConnection[]>;
  /** 400 naming the field the type refuses; 409 `provider_exists` for a name in use. */
  create(input: ProviderConnectionInput): Promise<{ id: string; name: string; type: string }>;
}
