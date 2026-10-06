import type { ListParams } from '@/lib/types/query';

import { ApiError } from './contract';
import type { FilesApi } from './files-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/**
 * Sends the bytes to object storage on the presigned URL. XMLHttpRequest rather than fetch because fetch reports
 * no upload progress. The request goes to the storage host, so it carries no console credentials.
 */
function putToStorage(ticket: { uploadUrl: string; method: 'PUT'; headers: Record<string, string> }, body: Blob, onProgress?: (f: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.method, ticket.uploadUrl);
    for (const [k, v] of Object.entries(ticket.headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new ApiError(`Storage refused the upload (${xhr.status}).`, xhr.status)));
    xhr.onerror = () => reject(new ApiError('The upload could not reach storage. Check the connection and try again.', 0));
    xhr.send(body);
  });
}

/** REST routes for files; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createFilesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): FilesApi {
  const base = '/files';
  return {
    createUpload: (i) => send('POST', `${base}/uploads`, i),
    transfer: (ticket, body, onProgress) => putToStorage(ticket, body, onProgress),
    completeUpload: (id, i) => send('POST', `${base}/uploads/${id}/complete`, i),
    get: (id) => get(`${base}/${id}`),
    list: (p) => get(`${base}?${qs(p)}`),
    downloadUrl: (id) => send('POST', `${base}/${id}/download-url`),
    versions: (id) => get(`${base}/${id}/versions`),
    references: (id) => get(`${base}/${id}/references`),
    setRetention: (ids, classId) => send('POST', `${base}/retention`, { ids, classId }),
    setLegalHold: (ids, hold, reason) => send('POST', `${base}/legal-hold`, { ids, hold, reason }),
    remove: (id) => send('DELETE', `${base}/${id}`),
    bulkRemove: (ids) => send('POST', `${base}/bulk-delete`, { ids }),
    exportEvidence: (i) => send('POST', `${base}/evidence-exports`, i),
    exportAudit: (p) => send('POST', `/audit/exports?${qs(p)}`),
    limits: () => get(`${base}/limits`),
    storage: {
      get: () => get('/settings/storage'),
      update: (i) => send('PUT', '/settings/storage', i),
      test: (environment) => send('POST', `/settings/storage/${environment}/test`),
    },
  };
}
