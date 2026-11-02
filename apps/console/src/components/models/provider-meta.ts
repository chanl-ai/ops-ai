import type { ProviderConnectionInput, ProviderType } from '@/lib/types/models';

export type ConnectableType = ProviderConnectionInput['type'];

/** Each connection type as a person reads it. */
export const PROVIDER_TYPES: Record<ProviderType, { label: string }> = {
  'azure-openai': { label: 'Azure OpenAI' },
  'openai-compatible': { label: 'OpenAI-compatible' },
  anthropic: { label: 'Anthropic' },
  scripted: { label: 'Scripted' },
};

/** The types models-service serves calls on, in the order the connect dialog offers them. */
export const CONNECTABLE_TYPES: ConnectableType[] = ['azure-openai', 'openai-compatible'];

/** What the endpoint field asks for, per type. */
export const ENDPOINT_FIELD: Record<ConnectableType, { placeholder: string; hint: string }> = {
  'azure-openai': { placeholder: 'e.g. https://contoso.openai.azure.com', hint: 'The resource’s endpoint, without /openai.' },
  'openai-compatible': { placeholder: 'e.g. https://api.openai.com/v1', hint: 'The base URL, ending in /v1.' },
};
