import type { ProviderType } from '@/lib/types/models';

/** Each provider type: its label, the endpoint it starts with, and the secret its key is saved under by default. */
export const PROVIDER_TYPES: Record<ProviderType, { label: string; baseUrl: string; secret: string; keyHint: string }> = {
  openai: { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', secret: 'OPENAI_API_KEY', keyHint: 'Starts with sk-' },
  anthropic: { label: 'Anthropic', baseUrl: 'https://api.anthropic.com/v1', secret: 'ANTHROPIC_API_KEY', keyHint: 'Starts with sk-ant-' },
  azure_openai: { label: 'Azure OpenAI', baseUrl: 'https://<resource>.openai.azure.com/openai', secret: 'AZURE_OPENAI_API_KEY', keyHint: 'Key 1 or Key 2 from the resource' },
  openai_compatible: { label: 'OpenAI-compatible', baseUrl: 'https://', secret: 'MODEL_PROVIDER_KEY', keyHint: 'The key your endpoint expects as a bearer token' },
};

export const PROVIDER_TYPE_ORDER: ProviderType[] = ['openai', 'anthropic', 'azure_openai', 'openai_compatible'];
