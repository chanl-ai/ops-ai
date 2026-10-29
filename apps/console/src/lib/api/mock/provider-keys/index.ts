import type { ProviderKey } from '@/lib/types/provider-keys';

import { ApiError } from '../../contract';
import type { ProviderKeysApi } from '../../provider-keys-contract';

const DAY = 86_400_000;
const SEED: ProviderKey[] = [
  { name: 'OPENAI', version: 2, createdBy: 'nadia@harborpine.example', createdAt: new Date(Date.now() - 40 * DAY).toISOString(), rotatedAt: new Date(Date.now() - 6 * DAY).toISOString() },
];
// The connections that sign in with a key, so a delete of one in use is refused as models-service refuses it.
const IN_USE: Record<string, string> = { OPENAI: 'openai' };

/** Sample keys for a console with no models-service; values are dropped on save, and nothing outlives a reload. */
export function createMockProviderKeys(): ProviderKeysApi {
  let rows = structuredClone(SEED);
  return {
    list: async () => structuredClone(rows),
    save: async (name) => {
      const before = rows.find((k) => k.name === name);
      const now = new Date().toISOString();
      const saved: ProviderKey = before ? { ...before, version: before.version + 1, rotatedAt: now } : { name, version: 1, createdBy: 'nadia@harborpine.example', createdAt: now, rotatedAt: null };
      rows = [...rows.filter((k) => k.name !== name), saved].sort((a, b) => a.name.localeCompare(b.name));
      return structuredClone(saved);
    },
    remove: async (name) => {
      if (IN_USE[name]) throw new ApiError(`Provider connection ${IN_USE[name]} signs in with ${name}.`, 409, undefined, 'key_in_use');
      if (!rows.some((k) => k.name === name)) throw new ApiError(`Model provider key ${name} was not found.`, 404, undefined, 'not_found');
      rows = rows.filter((k) => k.name !== name);
    },
  };
}
