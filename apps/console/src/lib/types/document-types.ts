/**
 * Document types (documents-service `/v1/document-types`): a team's named set of fields to read from a document,
 * saved as immutable versions, with sample files and the values each should read, and tests that run a version over
 * the samples and score every field. Types come from the generated SDK, so a field renamed in the API fails the typecheck.
 */

import type { OpsAI } from '@chanl-ai/ops-ai';

type Documents = OpsAI['raw']['documents'];
type Reply<K extends keyof Documents> = Awaited<ReturnType<Documents[K]>>;
type Body<K extends keyof Documents> = NonNullable<NonNullable<Parameters<Documents[K]>[0]>['body']>;

/** One record's values by field key. */
export type ExpectedRecord = Record<string, string | number | null>;
type Cell = string | number | null;

export type DocumentFieldType = 'text' | 'number' | 'money' | 'date' | 'enum';

/** documents-service types a version's fields as free-form objects; this is the shape the console reads and writes in them. */
export interface DocumentField {
  /** Lowercase letters, digits and underscores. */
  key: string;
  label?: string;
  type: DocumentFieldType;
  required?: boolean;
  description?: string;
  /** The allowed values of an `enum` field. */
  options?: string[];
  /** Confidence between 0 and 1 under which this field goes to review. */
  reviewBelow?: number;
  alwaysReview?: boolean;
}

export type DocumentTypeVersion = Omit<Reply<'document_types_get_version'>, 'fields'> & { fields: DocumentField[] };
export type DocumentTypeSample = Omit<Reply<'document_types_add_sample'>, 'expected'> & {
  /** One record for a single-record type, a list of records when the type reads several. */
  expected: ExpectedRecord | ExpectedRecord[];
};
export type DocumentType = Omit<Reply<'document_types_get_type'>, 'versions' | 'samples'> & {
  /** Newest first. */
  versions: DocumentTypeVersion[];
  samples: DocumentTypeSample[];
};
export type DocumentTypeList = Reply<'document_types_list_types'>;
export type DocumentTypeSummary = DocumentTypeList['data'][number];

// The schema lists `many`, `dateOrder` and `pageImages` as required in a request although documents-service defaults them.
type VersionBody = Body<'document_types_add_version'>;
export type DocumentTypeVersionInput = Omit<VersionBody, 'fields' | 'many' | 'dateOrder'> &
  Partial<Pick<VersionBody, 'many' | 'dateOrder'>> & { fields: DocumentField[] };
export type DocumentTypeInput = DocumentTypeVersionInput & Pick<Body<'document_types_create_type'>, 'id' | 'name' | 'description' | 'sampleFileId'>;
export type DocumentTypeSampleInput = { fileId: string; expected: ExpectedRecord | ExpectedRecord[] };

/** What testing a version spends, before it runs. */
export type DocumentTypeTestEstimate = Reply<'document_types_test_estimate'>;
export interface FieldComparison {
  expected: Cell;
  got: Cell;
  match: boolean;
}
type ServedRun = Reply<'document_types_get_test'>;
export type DocumentTypeTestStatus = ServedRun['status'];
export type DocumentTypeTestFieldScore = NonNullable<ServedRun['result']>['fields'][string];
export type DocumentTypeTestSampleResult = Omit<NonNullable<ServedRun['result']>['samples'][number], 'fields'> & {
  /** Per field, one comparison for each record that names it. */
  fields: Record<string, FieldComparison[]>;
};
export type DocumentTypeTestResult = Omit<NonNullable<ServedRun['result']>, 'samples'> & { samples: DocumentTypeTestSampleResult[] };
export type DocumentTypeTestRun = Omit<ServedRun, 'result'> & { result?: DocumentTypeTestResult | null };
