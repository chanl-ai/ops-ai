import type { DocumentField } from '@/lib/types/document-types';
import type { FieldRead, ReadField } from '@/lib/types/domain';

/** documents-service `/v1/documents/extractions`: one read of one file, with each field scored by the engine's checks. */
export interface Extraction {
  id: string;
  fileId: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'unreadable';
  /** Set once done: ok, review (some field is under the floor or failed a check) or unreadable. */
  outcome?: 'ok' | 'review' | 'unreadable' | null;
  documentType?: { id: string; version: number } | null;
  /** The type version's fields, in order. */
  schema?: ReadField[] | null;
  /** A type reading one record: each field's value, confidence and quote. */
  fields?: Record<string, FieldRead> | null;
  /** A type reading several records. */
  records?: { values: Record<string, unknown>; fields: Record<string, FieldRead> }[] | null;
  /** Keys of the fields a person should check. */
  needsReview?: string[] | null;
  /** The confidence a field must reach. */
  floor?: number | null;
  /** How many pages an unreadable file has; a full-text read's pages, each with its text and tables. */
  pages?: number | ExtractionPage[] | null;
  /** A full-text read's text, page after page in reading order. */
  text?: string | null;
  /** A proposed read: the fields the model proposed, in the document type's shape, and a suggested name. */
  proposal?: ExtractionProposal | null;
  /** The pages read when a page or token limit applied. */
  readPages?: number | null;
  /** True when the token limit stopped the read before every page was read. */
  partial?: boolean | null;
  error?: { code: string; message: string } | null;
}

export interface ExtractionInput {
  fileId: string;
  documentTypeId: string;
  /** The newest version when absent. */
  version?: number;
}

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

/** documents-service `/v1/documents/layout`: a file's pages, blocks in reading order, and words with confidence. */
export interface DocumentLayout {
  engine: string;
  pages: { number: number; width: number | null; height: number | null; source: 'text' | 'ocr' | 'none' }[];
  blocks: { id: string; page: number; kind: 'title' | 'heading' | 'line' | 'paragraph' | 'table'; text: string; box: number[] | null; order: number }[];
  /** `conf` is 1 on a text layer and the OCR engine's confidence on a scanned page. */
  words: { page: number; text: string; box: number[]; conf: number }[];
}
