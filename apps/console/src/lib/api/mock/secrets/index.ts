import { ApiError } from '../../contract';
import type { SecretsApi } from '../../secrets-contract';
import { respond } from '../runtime';
import type { SecretMeta } from '@/lib/types/secrets';

const NAME = /^[A-Z][A-Z0-9_]*$/;

/** Secrets in memory with the service's rules: names upper snake case, no duplicates, values never kept or returned. */
export function createSecretsMock(deps: { me: string }): SecretsApi {
  const at = new Date(Date.now() - 86_400_000 * 30).toISOString();
  const rows: SecretMeta[] = [
    { name: 'CORE_BANKING_KEY', version: 2, createdBy: 'Platform team', createdAt: at, rotatedAt: new Date(Date.now() - 86_400_000 * 3).toISOString(), lastUsedAt: new Date(Date.now() - 600_000).toISOString() },
    { name: 'EQUIFAX_TOKEN', version: 1, createdBy: 'Platform team', createdAt: at, rotatedAt: null, lastUsedAt: null },
  ];
  const find = (name: string) => rows.find((r) => r.name === name) ?? (() => { throw new ApiError(`Secret ${name} not found`, 404); })();
  return {
    list: () => respond(() => rows),
    create: (name, value) =>
      respond(() => {
        if (!NAME.test(name) || name.length > 120) throw new ApiError('Name the secret in upper case letters, digits and underscores, starting with a letter (e.g. STATEMENTS_KEY).', 400);
        if (!value) throw new ApiError('Enter the value.', 400);
        if (rows.some((r) => r.name === name)) throw new ApiError(`A secret named ${name} already exists. Rotate it to change its value.`, 409);
        const row = { name, version: 1, createdBy: deps.me, createdAt: new Date().toISOString(), rotatedAt: null, lastUsedAt: null };
        rows.push(row);
        return row;
      }),
    rotate: (name, value) =>
      respond(() => {
        if (!value) throw new ApiError('Enter the new value.', 400);
        const row = find(name);
        Object.assign(row, { version: row.version + 1, rotatedAt: new Date().toISOString() });
        return row;
      }),
    remove: (name) =>
      respond(() => {
        rows.splice(rows.indexOf(find(name)), 1);
      }),
  };
}
