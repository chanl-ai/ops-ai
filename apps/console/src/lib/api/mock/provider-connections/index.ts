import type { ProviderConnection } from '@/lib/types/models';

import { ApiError } from '../../contract';
import type { ProviderConnectionsApi } from '../../provider-connections-contract';

// Sample connections across an insurer, a retailer and a bank's own OpenAI account.
const SEED: ProviderConnection[] = [
  { id: 'prov_claims', name: 'claims-azure', type: 'azure-openai', baseUrl: 'https://contoso-claims.openai.azure.com', keyRef: 'AZURE_CLAIMS', apiVersion: '2024-10-21', region: 'swedencentral', observedRegion: 'Sweden Central', regionMismatch: null },
  { id: 'prov_retail', name: 'retail-eu', type: 'azure-openai', baseUrl: 'https://northwind-eu.openai.azure.com', keyRef: 'AZURE_RETAIL', apiVersion: 'v1', region: 'westeurope', observedRegion: null, regionMismatch: null },
  { id: 'openai-local', name: 'openai-local', type: 'openai-compatible', baseUrl: 'https://api.openai.com/v1', keyRef: 'OPENAI', apiVersion: null, region: null, observedRegion: null, regionMismatch: null },
  { id: 'prov_scripted', name: 'scripted', type: 'scripted', baseUrl: null, keyRef: null, apiVersion: null, region: null, observedRegion: null, regionMismatch: null },
];

/** Sample connections for a console with no models-service; nothing outlives a reload. */
export function createMockProviderConnections(): ProviderConnectionsApi {
  let rows = structuredClone(SEED);
  return {
    list: async () => structuredClone(rows),
    create: async (input) => {
      if (rows.some((r) => r.name === input.name)) throw new ApiError(`A provider connection named ${input.name} exists.`, 409, undefined, 'provider_exists');
      const row: ProviderConnection = { id: `prov_${rows.length + 1}`, apiVersion: null, region: null, observedRegion: null, regionMismatch: null, ...input };
      rows = [...rows, row].sort((a, b) => a.name.localeCompare(b.name));
      return { id: row.id, name: row.name, type: row.type };
    },
  };
}
