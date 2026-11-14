import { z } from 'zod';

/**
 * Whether the overview asks the person to set up the workspace's model: only an account admin (the one who can add a
 * key) of a workspace with no model provider key, and only once the keys have loaded, so it never flashes.
 */
export function needsModelSetup({ admin, keys }: { admin: boolean; keys: readonly { name: string }[] | undefined }): boolean {
  return admin && keys !== undefined && keys.length === 0;
}

export type SetupProvider = 'openai' | 'azure-openai' | 'anthropic';

/** The providers the first-run setup offers, in its order, as a person reads them. */
export const SETUP_PROVIDERS: { value: SetupProvider; label: string; hint: string }[] = [
  { value: 'openai', label: 'OpenAI', hint: 'A key from platform.openai.com.' },
  { value: 'azure-openai', label: 'Azure OpenAI', hint: 'Your resource’s endpoint and key; chat uses one of its deployments.' },
  { value: 'anthropic', label: 'Anthropic', hint: 'A key from console.anthropic.com.' },
];

/** Step one: the provider, and for Azure OpenAI the resource's endpoint and API version (v1 unless set). */
export const providerStep = z
  .object({ provider: z.enum(['openai', 'azure-openai', 'anthropic']), endpoint: z.string(), apiVersion: z.string() })
  .refine((v) => v.provider !== 'azure-openai' || /^https:\/\/[^/\s]+$/.test(v.endpoint.trim()), {
    message: 'Enter the resource’s endpoint, such as https://contoso.openai.azure.com.',
    path: ['endpoint'],
  });
export type ProviderStep = z.infer<typeof providerStep>;

/** Step two: the key as pasted; it goes to models-service once and leaves the page with the dialog. */
export const keyStep = z.object({ value: z.string().trim().min(1, 'Paste the provider’s key.') });

/** The name setup saves a provider's key under: one per provider, so running setup again replaces the key. */
export const setupKeyName = (provider: SetupProvider) => provider.toUpperCase().replace(/-/g, '_');

/** Where the saved key is tested and listed: the provider, plus Azure's endpoint and API version. */
export function keyWhere(step: ProviderStep): { provider: SetupProvider; endpoint?: string; apiVersion?: string } {
  return step.provider === 'azure-openai' ? { provider: step.provider, endpoint: step.endpoint.trim(), apiVersion: step.apiVersion.trim() || 'v1' } : { provider: step.provider };
}

/** What PUT /v1/models/chat-model is sent once a model is picked. */
export const chatModelBody = (step: ProviderStep, model: string) => ({ ...keyWhere(step), keyName: setupKeyName(step.provider), model });
