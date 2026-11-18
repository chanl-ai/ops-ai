import type { OpsAI } from '@chanl-ai/ops-ai';

import type { DocumentField } from '@/lib/types/document-types';
import type { FieldRead, ReadField } from '@/lib/types/domain';

type Documents = OpsAI['raw']['documents'];
type Reply<K extends keyof Documents> = Awaited<ReturnType<Documents[K]>>;

/** One page of a full-text read. */
export interface ExtractionPage {
  number: number;
  text: string;
  tables?: unknown[];
}

/** What a propose read suggests: a name and fields `POST /v1/document-types` accepts as they are. */
export interface ExtractionProposal {
  name: string;
  fields: DocumentField[];
}

/**
 * documents-service `/v1/documents/extractions`: one read of one file, with each field scored by the engine's checks.
 * The service types the schema, fields, records, pages and proposal as free-form objects; those five carry the shape the console reads.
 */
export type Extraction = Omit<Reply<'documents_get_extraction'>, 'schema' | 'fields' | 'records' | 'pages' | 'proposal'> & {
  /** The type version's fields, in order. */
  schema?: ReadField[] | null;
  /** A type reading one record: each field's value, confidence and quote. */
  fields?: Record<string, FieldRead> | null;
  /** A type reading several records. */
  records?: { values: Record<string, unknown>; fields: Record<string, FieldRead> }[] | null;
  /** How many pages an unreadable file has; a full-text read's pages, each with its text and tables. */
  pages?: number | ExtractionPage[] | null;
  /** A proposed read: the fields the model proposed, in the document type's shape, and a suggested name. */
  proposal?: ExtractionProposal | null;
};

export interface ExtractionInput {
  fileId: string;
  documentTypeId: string;
  /** The newest version when absent. */
  version?: number;
}

/** documents-service `/v1/documents/layout`: a file's pages, blocks in reading order, and words with confidence. */
export type DocumentLayout = Reply<'documents_compute_layout'>;
