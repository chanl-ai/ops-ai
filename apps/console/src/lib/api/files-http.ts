import type { ListParams } from '@/lib/types/query';

import { ApiError } from './contract';
import type { FilesApi } from './files-contract';
import { optionsQs } from './options';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown, headers?: Record<string, string>) => Promise<T>;

/**
 * Sends the bytes to object storage on the presigned URL. XMLHttpRequest rather than fetch because fetch reports
 * no upload progress. A presigned link goes to the storage host and carries no console credentials; `identity` is set
 * only when the link is files-service's own content route (local backend), which needs the person's token.
 */
export function putToStorage(ticket: { uploadUrl: string; method: 'PUT'; headers: Record<string, string> }, body: Blob, onProgress?: (f: number) => void, identity: Record<string, string> = {}) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.method, ticket.uploadUrl);
    for (const [k, v] of Object.entries({ ...ticket.headers, ...identity })) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new ApiError(`Storage refused the upload (${xhr.status}).`, xhr.status)));
    xhr.onerror = () => reject(new ApiError('The upload could not reach storage. Check the connection and try again.', 0));
    xhr.send(body);
  });
}

/** `/document-types` on documents-service (c-256); `get` and `send` carry the transport's identity and envelope. */
export function createDocumentTypesHttp(get: Get, send: Send): FilesApi['documentTypes'] {
  const base = '/document-types';
  const one = (id: string) => `${base}/${encodeURIComponent(id)}`;
  return {
    list: () => get(base),
    get: (id) => get(one(id)),
    create: (i) => send('POST', base, i),
    addVersion: (id, i) => send('POST', `${one(id)}/versions`, i),
    addSample: (id, i) => send('POST', `${one(id)}/samples`, i),
    removeSample: (id, sampleId) => send('DELETE', `${one(id)}/samples/${encodeURIComponent(sampleId)}`),
    estimate: (id, version) => get(`${one(id)}/versions/${version}/test-estimate`),
    startTest: (id, version) => send('POST', `${one(id)}/versions/${version}/test-runs`),
    test: (id, testId) => get(`${one(id)}/test-runs/${encodeURIComponent(testId)}`),
  };
}

/** documents-service's extraction routes: a read of one file with a document type, each retry keyed. */
export function createExtractionsRoutes(get: Get, send: Send): FilesApi['extractions'] {
  const base = '/documents/extractions';
  return {
    start: (input, key) => send('POST', base, input, { 'Idempotency-Key': key }),
    get: (id) => get(`${base}/${encodeURIComponent(id)}`),
    byFile: (fileId) => get(`${base}?${new URLSearchParams({ fileId, page: '1', pageSize: '20' })}`),
    correct: (id, key, value, record) => send('PATCH', `${base}/${encodeURIComponent(id)}/fields/${encodeURIComponent(key)}`, { value, ...(record !== undefined ? { record } : {}) }),
  };
}

/** REST routes for files; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createFilesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): FilesApi {
  const base = '/files';
  return {
    createUpload: (i) => send('POST', `${base}/uploads`, i),
    transfer: (ticket, body, onProgress) => putToStorage(ticket, body, onProgress),
    completeUpload: (id, i) => send('POST', `${base}/uploads/${id}/complete`, i),
    get: (id) => get(`${base}/${id}`),
    setData: (id, i) => send('PUT', `${base}/${id}/data`, i),
    readRequests: {
      start: (fileId, i, key) => send('POST', `${base}/${fileId}/read-requests`, i, { 'Idempotency-Key': key }),
      get: (fileId, key) => get(`${base}/${fileId}/read-requests/${encodeURIComponent(key)}`),
    },
    options: (p) => get(`${base}/options?${optionsQs(p)}`),
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
      test: (target) => send('POST', '/settings/storage/test', target),
      credentials: {
        list: () => get('/settings/storage/credentials'),
        set: (name, input) => send('PUT', `/settings/storage/credentials/${encodeURIComponent(name)}`, input),
        remove: (name) => send('DELETE', `/settings/storage/credentials/${encodeURIComponent(name)}`),
      },
    },
    documentTypes: createDocumentTypesHttp(get, send),
    extractions: createExtractionsRoutes(get, send),
  };
}
