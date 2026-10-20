import type { FilesApi } from './files-contract';
import { createTransport } from './http';

/**
 * Storage settings on files-service (`/v1/settings/storage`, c-100), the one files-service area the console calls
 * directly so far. The transport adds the signed-in person's token; files-service checks they are an admin on the
 * Security team.
 */
export function createStorageHttp(baseUrl: string): FilesApi['storage'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return {
    get: () => get('/settings/storage'),
    update: (input) => send('PUT', '/settings/storage', input),
    test: (target) => send('POST', '/settings/storage/test', target),
    credentials: {
      list: () => get('/settings/storage/credentials'),
      set: (name, input) => send('PUT', `/settings/storage/credentials/${encodeURIComponent(name)}`, input),
      remove: (name) => send('DELETE', `/settings/storage/credentials/${encodeURIComponent(name)}`),
    },
  };
}
