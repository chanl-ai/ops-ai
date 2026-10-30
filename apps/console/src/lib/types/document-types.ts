/**
 * Document types (files-service `/v1/document-types`): a team's named set of fields to read from a document,
 * saved as immutable versions, with sample files and the values each should read, and tests that run a version over
 * the samples and score every field.
 */

export type DocumentFieldType = "text" | "number" | "money" | "date" | "enum";

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

export interface DocumentTypeVersion {
  version: number;
  fields: DocumentField[];
  /** True when one document holds several records (a notice naming several people). */
  many: boolean;
  /** Confidence between 0 and 1 under which a read goes to review. */
  reviewBelow: number | null;
  note: string | null;
  createdBy: string;
  createdAt: string;
}

/** One record's values by field key. */
export type ExpectedRecord = Record<string, string | number | null>;

export interface DocumentTypeSample {
  id: string;
  fileId: string;
  /** The file's name. */
  name: string;
  /** One record for a single-record type, a list of records when the type reads several. */
  expected: ExpectedRecord | ExpectedRecord[];
  addedBy: string;
  addedAt: string;
}

export interface DocumentTypeSummary {
  id: string;
  name: string;
  description: string | null;
  latestVersion: number;
}

export interface DocumentTypeList {
  items: DocumentTypeSummary[];
  /** Whether the caller may create a document type in this team. */
  canCreate: boolean;
}

export interface DocumentType extends DocumentTypeSummary {
  team: string;
  createdBy: string;
  createdAt: string;
  /** Newest first. */
  versions: DocumentTypeVersion[];
  samples: DocumentTypeSample[];
  /** Whether the caller may save versions, change samples and run tests. */
  canEdit: boolean;
}

export interface DocumentTypeVersionInput {
  fields: DocumentField[];
  many?: boolean;
  reviewBelow?: number | null;
  note?: string;
}

export interface DocumentTypeInput extends DocumentTypeVersionInput {
  /** Generated when left out. */
  id?: string;
  name: string;
  description?: string;
  /** The file a proposed read was made from, kept as the type's first sample. */
  sampleFileId?: string;
}

export interface DocumentTypeSampleInput {
  fileId: string;
  expected: ExpectedRecord | ExpectedRecord[];
}

/** What testing a version spends, before it runs. */
export interface DocumentTypeTestEstimate {
  /** Samples the test reads, at most `capped`. */
  samples: number;
  /** One model call per sample. */
  calls: number;
  /** When every sample needs a second ask. */
  maxCalls: number;
  alias: string;
  /** The most samples one test reads. */
  capped: number;
  /** Decimal string, or null when the model's price is not known. */
  estimatedCost: string | null;
  maxCost?: string;
}

export type DocumentTypeTestStatus = "queued" | "running" | "done" | "failed";

export interface FieldComparison {
  expected: string | number | null;
  got: string | number | null;
  match: boolean;
}

export interface DocumentTypeTestSampleResult {
  sampleId: string;
  name: string;
  extractionId: string | null;
  status: string;
  /** Per field, one comparison for each record that names it. */
  fields: Record<string, FieldComparison[]>;
}

export interface DocumentTypeTestFieldScore {
  matches: number;
  misses: number;
  /** 0..1, or null when no sample names the field. */
  accuracy: number | null;
}

export interface DocumentTypeTestResult {
  samples: DocumentTypeTestSampleResult[];
  fields: Record<string, DocumentTypeTestFieldScore>;
  accuracy: number | null;
}

export interface DocumentTypeTestRun {
  id: string;
  typeId: string;
  version: number;
  status: DocumentTypeTestStatus;
  samples: number;
  askedBy: string;
  askedAt: string;
  result?: DocumentTypeTestResult;
  error?: string;
}
