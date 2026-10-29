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
