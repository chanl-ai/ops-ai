import { ApiError } from '../../contract';
import type { SecretsApi } from '../../secrets-contract';
import { list, respond } from '../runtime';
import type { SecretMeta, SecretUser } from '@/lib/types/secrets';

const NAME = /^[A-Z][A-Z0-9_]*$/;

/** Secrets in memory with the service's rules: names upper snake case, no duplicates, values never kept or returned. */
export function createSecretsMock(deps: { me: string; users?: () => Record<string, SecretUser[]> }): SecretsApi {
  const at = new Date(Date.now() - 86_400_000 * 30).toISOString();
  const rows: SecretMeta[] = [
    { name: 'CORE_BANKING_KEY', version: 2, createdBy: 'Platform team', createdAt: at, rotatedAt: new Date(Date.now() - 86_400_000 * 3).toISOString(), lastUsedAt: new Date(Date.now() - 600_000).toISOString(), usedBy: [], teams: null },
    { name: 'EQUIFAX_TOKEN', version: 1, createdBy: 'Platform team', createdAt: at, rotatedAt: null, lastUsedAt: null, usedBy: [], teams: ['team_ops'] },
  ];
  // Who reads each secret comes from the tool modules, as tools-service computes it from the operations.
  const withUsers = (r: SecretMeta): SecretMeta => ({ ...r, usedBy: deps.users?.()[r.name] ?? [] });
  const find = (name: string) => rows.find((r) => r.name === name) ?? (() => { throw new ApiError(`Secret ${name} not found`, 404); })();
  return {
    list: () => respond(() => rows.map(withUsers)),
    page: (p) => respond((m) => list(rows.map(withUsers).sort((a, b) => a.name.localeCompare(b.name)), p, { text: (r) => r.name, value: () => '', facetKeys: [] }, m)),
    setScope: (name, teams) =>
      respond(() => {
        const row = find(name);
        row.teams = teams && teams.length ? teams : null;
        return withUsers(row);
      }),
    create: (name, value, teams) =>
      respond(() => {
        if (!NAME.test(name) || name.length > 120) throw new ApiError('Name the secret in upper case letters, digits and underscores, starting with a letter (e.g. STATEMENTS_KEY).', 400);
        if (!value) throw new ApiError('Enter the value.', 400);
        if (rows.some((r) => r.name === name)) throw new ApiError(`A secret named ${name} already exists. Rotate it to change its value.`, 409);
        const row: SecretMeta = { name, version: 1, createdBy: deps.me, createdAt: new Date().toISOString(), rotatedAt: null, lastUsedAt: null, usedBy: [], teams: teams && teams.length ? teams : null };
        rows.push(row);
        return withUsers(row);
      }),
    rotate: (name, value) =>
      respond(() => {
        if (!value) throw new ApiError('Enter the new value.', 400);
        const row = find(name);
        Object.assign(row, { version: row.version + 1, rotatedAt: new Date().toISOString() });
        return withUsers(row);
      }),
    remove: (name) =>
      respond(() => {
        const users = withUsers(find(name)).usedBy;
        if (users.length) throw new ApiError(`${name} is read by ${users.map((u) => u.operation).join(', ')}. Remove it from those operations first.`, 409);
        rows.splice(rows.indexOf(find(name)), 1);
      }),
  };
}
