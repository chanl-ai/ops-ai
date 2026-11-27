import type { CatalogModel, ProviderConnection, ProviderTypeInfo } from '@/lib/types/models';

import { ApiError } from '../../contract';
import { list, respond } from '../runtime';
import type { ProviderConnectionsApi } from '../../provider-connections-contract';
import type { ProviderKeysApi } from '../../provider-keys-contract';

// Sample connections across an insurer, a retailer and a bank's own OpenAI account.
const SEED: ProviderConnection[] = [
  { id: 'prov_claims', name: 'claims-azure', type: 'azure-openai', baseUrl: 'https://contoso-claims.openai.azure.com', keyRef: 'AZURE_CLAIMS', apiVersion: '2024-10-21', region: 'swedencentral', observedRegion: 'Sweden Central', regionMismatch: null },
  { id: 'prov_retail', name: 'retail-eu', type: 'azure-openai', baseUrl: 'https://northwind-eu.openai.azure.com', keyRef: 'AZURE_RETAIL', apiVersion: 'v1', region: 'westeurope', observedRegion: null, regionMismatch: null },
  { id: 'openai-local', name: 'openai-local', type: 'openai', baseUrl: 'https://api.openai.com/v1', keyRef: 'OPENAI', apiVersion: null, region: null, observedRegion: null, regionMismatch: null },
  { id: 'prov_scripted', name: 'scripted', type: 'scripted', baseUrl: null, keyRef: null, apiVersion: null, region: null, observedRegion: null, regionMismatch: null },
];

const KEY = { type: 'string', title: 'API key', description: 'Saved sealed as the account’s provider key; never shown again.', 'x-secret': true } as const;
// The registry's shape (models-service `registry/providers`): each type's fields as JSON Schema.
const TYPES: ProviderTypeInfo[] = [
  { id: 'openai', label: 'OpenAI', icon: 'openai', listsModels: true, catalogued: true, connection: { type: 'object', properties: { apiKey: KEY }, required: ['apiKey'] } },
  {
    id: 'azure-openai',
    label: 'Azure OpenAI',
    icon: 'azure',
    listsModels: true,
    catalogued: true,
    connection: {
      type: 'object',
      properties: {
        baseUrl: { type: 'string', title: 'Endpoint', description: 'The resource’s endpoint, with no path.', format: 'uri', 'x-column': 'base_url' },
        apiVersion: { type: 'string', title: 'API version', description: 'v1, or a dated version from 2024-10-21 on.', default: 'v1', 'x-column': 'api_version' },
        region: { type: 'string', title: 'Region', description: 'Optional: an answer from another region is flagged.', 'x-column': 'region' },
        apiKey: KEY,
      },
      required: ['baseUrl', 'apiVersion', 'apiKey'],
    },
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    icon: 'anthropic',
    listsModels: true,
    catalogued: true,
    connection: {
      type: 'object',
      properties: { baseUrl: { type: 'string', title: 'Base URL', description: 'Leave as is for Anthropic’s own API.', format: 'uri', default: 'https://api.anthropic.com/v1', 'x-column': 'base_url' }, apiKey: KEY },
      required: ['apiKey'],
    },
  },
  { id: 'google', label: 'Google Gemini', icon: 'google', listsModels: true, catalogued: true, connection: { type: 'object', properties: { apiKey: KEY }, required: ['apiKey'] } },
  {
    id: 'bedrock',
    label: 'Amazon Bedrock',
    icon: 'aws',
    listsModels: true,
    catalogued: true,
    connection: {
      type: 'object',
      properties: {
        region: { type: 'string', title: 'Region', description: 'The AWS region the models run in, such as us-east-1.', 'x-column': 'region' },
        accessKeyId: { type: 'string', title: 'Access key ID', 'x-secret': true },
        secretAccessKey: { type: 'string', title: 'Secret access key', 'x-secret': true },
      },
      required: ['region', 'accessKeyId', 'secretAccessKey'],
    },
  },
  {
    id: 'openai-compatible',
    label: 'OpenAI-compatible URL',
    icon: 'plug',
    listsModels: true,
    catalogued: false,
    connection: {
      type: 'object',
      properties: { baseUrl: { type: 'string', title: 'Base URL', description: 'Any endpoint that speaks OpenAI’s chat API, ending in /v1.', format: 'uri', 'x-column': 'base_url' }, apiKey: { ...KEY, description: 'Optional for an endpoint that takes no key.' } },
      required: ['baseUrl'],
    },
  },
];

const CATALOG: CatalogModel[] = [
  { id: 'claude-sonnet-4-5', name: 'Claude Sonnet 4.5', context: 200000, output: 64000, reasoning: true, images: true, inputPerMillion: 3, outputPerMillion: 15, knobs: ['temperature', 'top_p', 'top_k', 'max_tokens', 'thinking_budget'] },
  { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', context: 200000, output: 64000, reasoning: true, images: true, inputPerMillion: 1, outputPerMillion: 5, knobs: ['temperature', 'top_p', 'top_k', 'max_tokens', 'thinking_budget'] },
  { id: 'gpt-4.1-mini', name: 'GPT-4.1 mini', context: 1000000, output: 32768, reasoning: false, images: true, inputPerMillion: 0.4, outputPerMillion: 1.6, knobs: ['temperature', 'top_p', 'max_tokens'] },
  { id: 'o4-mini', name: 'o4-mini', context: 200000, output: 100000, reasoning: true, images: true, inputPerMillion: 1.1, outputPerMillion: 4.4, knobs: ['max_tokens', 'reasoning_effort'] },
];

/** Sample connections for a console with no models-service; nothing outlives a reload. */
export function createMockProviderConnections(keys: ProviderKeysApi): ProviderConnectionsApi & { catalogModels: (providerId: string) => CatalogModel[] } {
  let rows = structuredClone(SEED);
  // Only a catalogued type has models in the catalog; a URL's models are listed by its key, not here.
  const catalogModels = (providerId: string) => (rows.find((r) => r.id === providerId && TYPES.find((t) => t.id === r.type)?.catalogued) ? CATALOG : []);
  return {
    catalogModels,
    list: async (p) => list(rows, p, { text: (c) => `${c.name} ${c.type}`, value: () => '', facetKeys: [], id: (c) => c.id }, 'normal'),
    create: async (input) => {
      // The secrets a connection is made with are saved as its key, as models-service does in the same request.
      if (input.secrets && input.keyRef) await keys.save(input.keyRef, 'sealed');
      if (rows.some((r) => r.name === input.name)) throw new ApiError(`A provider connection named ${input.name} exists.`, 409, undefined, 'provider_exists');
      const row: ProviderConnection = { id: `prov_${rows.length + 1}`, baseUrl: input.baseUrl ?? null, keyRef: input.keyRef ?? null, apiVersion: input.apiVersion ?? null, region: input.region ?? null, observedRegion: null, regionMismatch: null, name: input.name, type: input.type };
      rows = [...rows, row].sort((a, b) => a.name.localeCompare(b.name));
      return { id: row.id, name: row.name, type: row.type };
    },
    types: () => respond(() => TYPES),
    catalog: (providerId) => respond(() => catalogModels(providerId)),
  };
}
