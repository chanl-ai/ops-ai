import type { ChatModelChoice, KeyCheck, KeyWhere, ProviderModel, ProviderKey } from '@/lib/types/provider-keys';

/**
 * The account's model provider keys on models-service: account admins (settings.manage, held in
 * the Security team) save them; only models-service reads a value, and no team sees one.
 */
export interface ProviderKeysApi {
  /** 403 `admin_only` for anyone else. */
  list(): Promise<ProviderKey[]>;
  /** Saves the key, or replaces the value of the one with this name. The value is never returned. */
  save(name: string, value: string): Promise<ProviderKey>;
  /** 409 `key_in_use` while a provider connection signs in with it; 404 when none has the name. */
  remove(name: string): Promise<void>;
  /** Asks the provider whether it accepts the saved key; a refusal is `ok: false` with a reason, not an error. */
  check(name: string, where: KeyWhere): Promise<KeyCheck>;
  /** The models (Azure OpenAI: deployments) the saved key reaches; 422 `key_refused` when the provider refuses it. */
  models(name: string, where: KeyWhere): Promise<ProviderModel[]>;
  /** Points chat (the default and assistant aliases) at a model the saved key lists. */
  setChatModel(choice: ChatModelChoice): Promise<{ providerId: string; model: string; aliases: string[] }>;
}
