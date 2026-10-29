import { createTransport } from './http';
import type { ProviderKeysApi } from './provider-keys-contract';
import { createProviderKeysHttp } from './provider-keys-http';

/**
 * The provider key routes on models-service's own URL (NEXT_PUBLIC_OPS_MODELS_API_URL), the one models-service area the
 * console calls. The transport adds the signed-in person's token; models-service checks they are an account admin.
 */
export function createModelsHttp(baseUrl: string): ProviderKeysApi {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createProviderKeysHttp(get, send);
}
