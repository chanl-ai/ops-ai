/** Govern › Models (c-177): the model providers a workspace connects, as models-service serves them. */

export type ProviderType = 'openai' | 'anthropic' | 'azure_openai' | 'openai_compatible';

/** The last connection test: a call to the provider's model list with its key. */
export interface ProviderHealth {
  status: 'ok' | 'failed' | 'untested';
  /** When the test ran, ISO; null before the first. */
  at: string | null;
  latencyMs?: number | null;
  /** The provider's own refusal, as it gave it ("401 invalid api key"); never the key. */
  error?: string | null;
  /** How many models the key may call, from the provider's list. */
  models?: number | null;
}

export interface ModelProvider {
  id: string;
  name: string;
  type: ProviderType;
  baseUrl: string;
  /** The workspace secret holding the key (Govern › Settings › Secrets); null for a provider that takes none. */
  keySecret: string | null;
  /** Whether that secret exists; a connection naming a missing secret cannot call the provider. */
  keySet: boolean;
  health: ProviderHealth;
  /** The aliases (what agents and workflows pick) that route to this provider. */
  aliases: string[];
}

/** Connecting a provider: the key is saved as a workspace secret named `keySecret`, or an existing one is named. */
export interface ProviderInput {
  name: string;
  type: ProviderType;
  baseUrl: string;
  keySecret: string;
  /** A new key to save under `keySecret`; absent when the secret already holds it. */
  key?: string;
}
