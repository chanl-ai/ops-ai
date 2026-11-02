/** Govern › Settings › Model providers: the account's provider connections, as models-service serves them. */

/** The connection types models-service knows; the console connects the two it serves to callers. */
export type ProviderType = 'openai-compatible' | 'azure-openai' | 'anthropic' | 'scripted';

/** Where an alias's calls go, and the name of the saved key they sign in with; a key itself never comes back. */
export interface ProviderConnection {
  id: string;
  name: string;
  type: ProviderType;
  /** The endpoint: a base URL ending in /v1, or an Azure resource's endpoint; null for scripted. */
  baseUrl: string | null;
  /** The model provider key's name (Keys on the same page); null for an endpoint that takes none. */
  keyRef: string | null;
  /** Azure OpenAI only: `v1` or a dated version. */
  apiVersion: string | null;
  /** Azure OpenAI only: the region the resource runs in. */
  region: string | null;
  /** Azure OpenAI only: the region Azure last answered from; null until the first call. */
  observedRegion: string | null;
  /** `answered from <region>, expected <region>` when Azure answered from another region; computed by models-service. */
  regionMismatch: string | null;
}

/** Connecting a provider: only the picked type's fields are sent. */
export interface ProviderConnectionInput {
  name: string;
  type: 'openai-compatible' | 'azure-openai';
  baseUrl: string;
  keyRef: string | null;
  apiVersion?: string;
  region?: string;
}
