import type { FilesApi } from './files-contract';
import { ApiError } from './contract';
import { putToStorage } from './files-http';
import { createTransport } from './http';
import { optionsQs } from './options';
import { fetchWithIdentity, identityHeaders } from './request-identity';

const unavailable = (what: string) => () => Promise.reject(new ApiError(`${what} is not on files-service yet.`, 501));

/**
 * The Files page's calls on files-service (`/v1/files`, c-126): the list with its views, counts and facets, a file
 * with its references and versions, download, delete, legal hold, the file picker's options, and every upload.
 * Uploads of every purpose go here (c-466): an upload stored anywhere else gets an id that the list, the picker and
 * every service reading files by id cannot find, and files-service is what reuses a team's file with the same bytes.
 * Retention and evidence export are not offered there yet; the page hides those actions.
 */
export function createFilesServiceHttp(
  baseUrl: string,
): Pick<FilesApi, 'list' | 'get' | 'setData' | 'readRequests' | 'downloadUrl' | 'versions' | 'references' | 'remove' | 'bulkRemove' | 'setLegalHold' | 'setRetention' | 'exportEvidence' | 'createUpload' | 'transfer' | 'completeUpload' | 'options'> {
  const { get, send, qs } = createTransport(`${baseUrl}/v1`);
  const filesHost = new URL(baseUrl).origin;
  return {
    createUpload: (i) => send('POST', '/files/uploads', i),
    // A local backend's upload link is files-service's own content route, which needs the person's token.
    transfer: (ticket, body, onProgress) => putToStorage(ticket, body, onProgress, new URL(ticket.uploadUrl, filesHost).origin === filesHost ? identityHeaders() : {}),
    completeUpload: (id) => send('POST', `/files/uploads/${id}/complete`),
    options: (p) => get(`/files/options?${optionsQs(p)}`),
    list: (p) => get(`/files?${qs(p)}`),
    get: (id) => get(`/files/${id}`),
    setData: (id, i) => send('PUT', `/files/${id}/data`, i),
    readRequests: {
      start: (fileId, i, key) => send('POST', `/files/${fileId}/read-requests`, i, { 'Idempotency-Key': key }),
      get: (fileId, key) => get(`/files/${fileId}/read-requests/${encodeURIComponent(key)}`),
    },
    // On the local backend the link is the service's own content route, which needs the person's token, so the bytes
    // are fetched with it and handed to the page as a blob link. Presigned storage links are opened as they are.
    downloadUrl: async (id) => {
      const link = await send<{ url: string; expiresAt: string; ttlSeconds: number }>('POST', `/files/${id}/download-url`);
      if (new URL(link.url, filesHost).origin !== filesHost) return link;
      const res = await fetchWithIdentity(new URL(link.url, filesHost).toString());
      if (!res.ok) throw new ApiError(`The download was refused (${res.status}).`, res.status);
      return { ...link, url: URL.createObjectURL(await res.blob()) };
    },
    versions: async (id) => (await get<{ versions: Awaited<ReturnType<FilesApi['versions']>> }>(`/files/${id}`)).versions,
    references: async (id) => (await get<{ references: Awaited<ReturnType<FilesApi['references']>> }>(`/files/${id}`)).references,
    remove: (id) => send('DELETE', `/files/${id}`),
    bulkRemove: (ids) => send('POST', '/files/bulk-delete', { ids }),
    setLegalHold: (ids, hold, reason) => send('POST', '/files/legal-hold', { ids, hold, reason }),
    setRetention: unavailable('Setting retention'),
    exportEvidence: unavailable('Evidence export'),
  };
}
