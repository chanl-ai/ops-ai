import type { SecretMeta } from '@/lib/types/secrets';

/**
 * Credentials tool calls send, kept encrypted by tools-service and never returned. A name is upper snake case
 * (`STATEMENTS_KEY`); creating a taken name is refused (409) and points at rotate; a rotation reaches the next call.
 */
export interface SecretsApi {
  list(): Promise<SecretMeta[]>;
  create(name: string, value: string): Promise<SecretMeta>;
  rotate(name: string, value: string): Promise<SecretMeta>;
  remove(name: string): Promise<void>;
}
