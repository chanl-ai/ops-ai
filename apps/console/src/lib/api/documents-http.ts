import type { FilesApi } from './files-contract';
import { createDocumentTypesHttp, createExtractionsRoutes } from './files-http';
import { createTransport } from './http';

/**
 * Document types on documents-service (`/v1/document-types`, c-256). Files keeps the bytes; documents-service reads
 * them as the person's team and owns the types, their versions, samples and test runs.
 */
export function createDocumentsHttp(baseUrl: string): FilesApi['documentTypes'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createDocumentTypesHttp(get, send);
}

/** Extractions on documents-service (`/v1/documents/extractions`): a read of one file with a document type. */
export function createExtractionsHttp(baseUrl: string): FilesApi['extractions'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createExtractionsRoutes(get, send);
}
