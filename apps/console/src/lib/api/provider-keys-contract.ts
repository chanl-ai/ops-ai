import type { ProviderKey } from '@/lib/types/provider-keys';

/**
 * The account's model provider keys on models-service (owner, 2026-10-27): account admins (settings.manage, held in
 * the Security team) save them; only models-service reads a value, and no team sees one.
 */
export interface ProviderKeysApi {
  /** 403 `admin_only` for anyone else. */
  list(): Promise<ProviderKey[]>;
  /** Saves the key, or replaces the value of the one with this name. The value is never returned. */
  save(name: string, value: string): Promise<ProviderKey>;
  /** 409 `key_in_use` while a provider connection signs in with it; 404 when none has the name. */
  remove(name: string): Promise<void>;
}
