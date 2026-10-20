import type { FilePurpose } from '@/lib/types/files';

import type { FilesApi } from './files-contract';
import { ApiError } from './contract';
import { putToStorage } from './files-http';
import { createTransport } from './http';
import { optionsQs } from './options';
import { fetchWithIdentity, identityHeaders } from './request-identity';

/** Upload purposes whose files a service reads from files-service by id. */
// A workflow run's files go to files-service too, since the run's steps read them there by id (c-273).
const ON_FILES_SERVICE = new Set<FilePurpose>(['knowledge_source', 'case_attachment']);

const unavailable = (what: string) => () => Promise.reject(new ApiError(`${what} is not on files-service yet.`, 501));

/**
 * The Files page's calls on files-service (`/v1/files`, c-126): the list with its views, counts and facets, a file
 * with its references and versions, download, delete, legal hold, and the file picker's options. Knowledge uploads go
 * to files-service too (c-159), because kb-service adds a file to a base only by its files-service id; uploads for
 * other purposes stay on `fallback` until their services read from files-service. Retention and evidence export are
 * not offered there yet; the page hides those actions.
 */
export function createFilesServiceHttp(
  baseUrl: string,
  fallback: Pick<FilesApi, 'createUpload' | 'transfer' | 'completeUpload'>,
): Pick<FilesApi, 'list' | 'get' | 'setData' | 'readRequests' | 'downloadUrl' | 'versions' | 'references' | 'remove' | 'bulkRemove' | 'setLegalHold' | 'setRetention' | 'exportEvidence' | 'createUpload' | 'transfer' | 'completeUpload' | 'options'> {
  const { get, send, qs } = createTransport(`${baseUrl}/v1`);
  const filesHost = new URL(baseUrl).origin;
  // Uploads this client started on files-service, so completing one goes back to the service that issued it.
  const issued = new Set<string>();
  return {
    createUpload: async (i) => {
      if (!ON_FILES_SERVICE.has(i.purpose)) return fallback.createUpload(i);
      const ticket = await send<Awaited<ReturnType<FilesApi['createUpload']>>>('POST', '/files/uploads', i);
      issued.add(ticket.fileId);
      return ticket;
    },
    transfer: (ticket, body, onProgress) =>
      issued.has(ticket.fileId) ? putToStorage(ticket, body, onProgress, new URL(ticket.uploadUrl, filesHost).origin === filesHost ? identityHeaders() : {}) : fallback.transfer(ticket, body, onProgress),
    completeUpload: (id, i) => (issued.has(id) ? send('POST', `/files/uploads/${id}/complete`) : fallback.completeUpload(id, i)),
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
