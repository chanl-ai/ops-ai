import { createTransport } from './http';
import type { ProviderConnectionsApi } from './provider-connections-contract';
import { createProviderConnectionsHttp } from './provider-connections-http';
import type { ProviderKeysApi } from './provider-keys-contract';
import { createProviderKeysHttp } from './provider-keys-http';

/**
 * The provider key and connection routes on models-service's own URL (NEXT_PUBLIC_OPS_MODELS_API_URL), the
 * models-service areas the console calls. The transport adds the signed-in person's token; models-service checks they
 * are an account admin.
 */
export function createModelsHttp(baseUrl: string): { providerKeys: ProviderKeysApi; providerConnections: ProviderConnectionsApi } {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return { providerKeys: createProviderKeysHttp(get, send), providerConnections: createProviderConnectionsHttp(get, send) };
}
