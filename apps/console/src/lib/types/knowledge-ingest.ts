/**
 * How a source turns its items into searchable chunks: splitting strategies, presets, table columns, split
 * previews, required metadata, versions and duplicates.
 */

/**
 * One ingestion step. `structure`, `fixed`, `topic` and `table_rows` split the document (pick one); the rest
 * add to a split: `faq` indexes generated questions, `context_headers` prefixes each chunk with its title and
 * section path, `parent_child` indexes small chunks and returns their parent section, `clean` strips HTML and
 * boilerplate before splitting.
 */
export type IngestStrategy = 'structure' | 'fixed' | 'topic' | 'faq' | 'context_headers' | 'parent_child' | 'table_rows' | 'clean';

export type IngestPresetId = 'policy_manual' | 'help_centre' | 'rate_table' | 'email_templates' | 'custom';

/** How a table column is used by `table_rows`: searched, kept as filterable metadata, or dropped. */
export type ColumnRole = 'searchable' | 'metadata' | 'ignored';

export interface TableColumn {
  name: string;
  role: ColumnRole;
  /** The column that names a row in citations and lookups, such as the product. One per table. */
  key?: boolean;
}

/** AI steps (topic, FAQ, metadata extraction) call a model at ingest, so the knowledge owner approves them first. */
export interface IngestApproval {
  status: 'not_needed' | 'pending' | 'approved';
  /** The AI steps the approval covers; adding another makes it pending again. */
  approvedSteps: string[];
  requestedBy?: string;
  decidedBy?: string;
  decidedAt?: string;
}

export interface IngestSettings {
  preset: IngestPresetId;
  strategies: IngestStrategy[];
  /** Target chunk size and overlap, in tokens. */
  size: number;
  overlap: number;
  /** Size of the small indexed chunks under `parent_child`, in tokens. */
  childSize: number;
  /** Questions generated per section under `faq`. */
  questionsPerSection: number;
  /** Column roles under `table_rows`. */
  columns: TableColumn[];
  /** Model alias the AI steps call at ingest. */
  model: string;
  approval: IngestApproval;
}

/** A seeded document the split preview can run on. */
export interface SampleDocument {
  id: string;
  title: string;
  sourceName: string;
  format: 'policy' | 'table' | 'article' | 'email' | 'faq';
  version?: string;
  effectiveDate?: string;
  /** Column names when the sample is a table. */
  columns?: string[];
}

export interface PreviewChunk {
  index: number;
  kind: 'chunk' | 'row' | 'parent';
  /** What a query returns. */
  text: string;
  /** What search matches against: the text plus headers, questions or child chunks. */
  indexedText: string;
  sectionPath: string[];
  questions?: string[];
  /** Small indexed chunks under a parent section. */
  children?: string[];
  metadata: Record<string, string>;
  tokens: number;
}

export interface SplitCounts {
  chunks: number;
  /** Entries in the index: chunks, child chunks and generated questions. */
  indexedUnits: number;
  questions: number;
  tokens: number;
  /** Model calls the AI steps make for this document. */
  modelCalls: number;
  /** Characters of HTML and boilerplate `clean` removed. */
  removedChars: number;
}

export interface SplitPreview {
  sampleId: string;
  title: string;
  strategies: IngestStrategy[];
  chunks: PreviewChunk[];
  counts: SplitCounts;
  /** Why a step was skipped or what it changed, in product language. */
  notes: string[];
}

export interface SplitPreviewInput {
  sampleId: string;
  ingest: IngestSettings;
  parsing: { ocr: boolean; tables: boolean; vision: boolean };
  metadataMapping?: { key: string; from: string }[];
}

export type VersionStatus = 'current' | 'superseded' | 'scheduled';

/** One version of a document, newest first on the item page. */
export interface ItemVersionRow {
  itemId: string;
  title: string;
  version: string;
  effectiveDate: string;
  status: VersionStatus;
  digest: string;
  sourceName: string;
  supersededBy?: string;
}

/** Why an item is held out of search, and which knowledge bases require the missing fields. */
export interface HeldReason {
  missing: string[];
  kbNames: string[];
}
