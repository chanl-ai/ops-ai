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
  pages?: number | null;
  error?: { code: string; message: string } | null;
}

export interface ExtractionInput {
  fileId: string;
  documentTypeId: string;
  /** The newest version when absent. */
  version?: number;
}
