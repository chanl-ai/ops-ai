/** An account's model provider key (models-service `/v1/provider-keys`): its name and history, never its value. */
export interface ProviderKey {
  /** The name a provider connection's key reference gives, such as OPENAI. */
  name: string;
  /** 1 when first saved, one more on each replacement. */
  version: number;
  createdBy: string;
  createdAt: string;
  /** When the value was last replaced; null until then. */
  rotatedAt: string | null;
}

/** Which provider a key is for, and for Azure OpenAI the resource's endpoint and API version. */
export interface KeyWhere {
  provider: 'openai' | 'azure-openai' | 'anthropic';
  endpoint?: string;
  apiVersion?: string;
}

export interface KeyCheck {
  ok: boolean;
  reason?: string | null;
  /** How many models or deployments the key reaches. */
  models: number;
}

/** A model the key reaches; for Azure OpenAI `id` is the deployment and `model` the model behind it. */
export interface ProviderModel {
  id: string;
  model?: string | null;
}

export interface ChatModelChoice extends KeyWhere {
  keyName: string;
  model: string;
}
