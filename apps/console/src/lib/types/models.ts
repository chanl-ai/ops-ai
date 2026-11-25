/** Settings › Models: the account’s provider connections, aliases and catalog, as models-service serves them. */

/** A provider type's id from models-service's registry (GET /v1/models/provider-types); the console holds no list of them. */
export type ProviderType = string;

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

/**
 * Connecting a provider: the registry type's `x-column` fields go top level, its `x-secret` fields in `secrets`, saved
 * sealed under `keyRef`. A type that takes no key sends neither.
 */
export interface ProviderConnectionInput {
  name: string;
  type: ProviderType;
  baseUrl?: string | null;
  keyRef?: string | null;
  apiVersion?: string | null;
  region?: string | null;
  secrets?: Record<string, string>;
}

/** A property of a registry type's JSON Schema; the keys the form reads are in `components/shared/schema-form.tsx`. */
export interface ConnectionSchema {
  type?: string;
  properties?: Record<string, ConnectionSchemaField>;
  required?: string[];
}
export interface ConnectionSchemaField {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  format?: string;
  pattern?: string;
  /** The connection column the value is saved in; absent for none. */
  'x-column'?: 'base_url' | 'api_version' | 'region';
  /** Saved sealed as the account's provider key, never returned. */
  'x-secret'?: boolean;
}

/** One provider type a connection can be made of, as models-service lists it. */
export interface ProviderTypeInfo {
  id: string;
  label: string;
  icon: string;
  connection: ConnectionSchema;
  /** Whether the type's key can be tested and its models listed. */
  listsModels: boolean;
  /** Whether its models are in the catalog (capabilities, context, price). */
  catalogued: boolean;
}

/** A model the catalog holds for a connection: what it can do, its limits and list prices (per million tokens). */
export interface CatalogModel {
  id: string;
  name: string;
  context: number | null;
  output: number | null;
  reasoning: boolean;
  images: boolean;
  inputPerMillion: number | null;
  outputPerMillion: number | null;
  knobs: string[];
}

/** An alias version as models-service lists it: the model it calls, on which connection, and what it is cleared for. */
export interface ModelAliasRow {
  name: string;
  version: number;
  kind: string;
  providerId: string;
  /** The connection's name, from models-service. */
  providerName?: string | null;
  modelId: string;
  clearedSensitivity: string;
  inputPerMillion: string;
  outputPerMillion: string;
  images?: boolean;
  reasoningEffort?: string | null;
  status: string;
}

/** Making an alias, or saving a new version of one (the name is the path). */
export interface ModelAliasInput {
  name?: string;
  providerId: string;
  modelId: string;
  clearedSensitivity: string;
  inputPerMillion?: number;
  outputPerMillion?: number;
  images?: boolean;
}

/** One knob of an alias's model, as the knobs route's JSON Schema describes it. */
export interface KnobSchema {
  type: 'number' | 'integer' | 'string' | 'boolean';
  title?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  default?: number | string;
  enum?: string[];
}
/** The settings an agent on an alias may save: only the knobs its model takes. */
export interface AliasKnobs {
  alias: string;
  version: number;
  modelId: string;
  catalogued: boolean;
  knobs: { type: 'object'; properties: Record<string, KnobSchema> };
}
