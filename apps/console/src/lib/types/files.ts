import type { AuditEntry } from './governance';

/**
 * Files: every byte the platform stores goes through the Files API. Other APIs take and return a `fileId`,
 * never raw bytes. Bytes travel browser → object storage on a short-lived presigned URL, so the control plane
 * holds metadata only (spec 10).
 */
export type FilePurpose = 'knowledge_source' | 'chat_attachment' | 'case_attachment' | 'document_type_sample' | 'email_body' | 'test_import' | 'evidence_bundle' | 'export' | 'tool_spec' | 'avatar' | 'skill_resource' | 'idp_metadata';
export type ScanStatus = 'pending' | 'clean' | 'infected' | 'failed';
export type FileSensitivity = 'public' | 'internal' | 'confidential' | 'restricted';
export type StorageBackend = 's3' | 'azure_blob';
export type StorageEnvironment = 'dev' | 'test' | 'prod';

/** Where the object sits. Returned to platform admins only; everyone else gets `undefined`. */
export interface StorageLocation {
  backend: StorageBackend;
  environment: StorageEnvironment;
  /** Bucket (S3) or container (Azure Blob). */
  container: string;
  key: string;
  region: string;
  /** KMS key alias (S3) or encryption scope (Azure Blob). */
  encryption: string;
  /** Object Lock (S3) or immutability policy (Azure Blob) applies to this object. */
  locked: boolean;
}

export type FileReferenceType = 'source' | 'case' | 'chat' | 'eval_set' | 'test_set' | 'evidence' | 'export' | 'tool_module' | 'skill';

/** Something that uses the file. Removing a referenced file is refused while any reference exists. */
export interface FileReference {
  type: FileReferenceType;
  id: string;
  name: string;
  href?: string;
  addedAt: string;
  /** Set while the file is quarantined: what the referencing record shows instead of the content. */
  blocked?: string;
}

export interface FileVersion {
  version: number;
  digest: string;
  size: number;
  uploadedBy: string;
  uploadedAt: string;
  current: boolean;
}

export interface FileScan {
  status: ScanStatus;
  engine?: string;
  at?: string;
  /** Signature name when infected, error when failed. */
  detail?: string;
}

export interface FileRetention {
  classId: string;
  className: string;
  /** yyyy-mm-dd; null means kept until a person deletes it. */
  deleteAfter: string | null;
}

export interface LegalHold {
  by: string;
  at: string;
  reason: string;
}

export interface FileRecord {
  id: string;
  name: string;
  mime: string;
  size: number;
  /** sha256 of the current version, hex. Identical content in one team is stored once. */
  digest: string;
  purpose: FilePurpose;
  /** Owner group of the team that uploaded it; scoping follows it. */
  team: string;
  uploadedBy: string;
  uploadedAt: string;
  scan: FileScan;
  sensitivity: FileSensitivity;
  /** True while the classification is the platform's suggestion and no person has confirmed it. */
  sensitivitySuggested: boolean;
  retention: FileRetention;
  legalHold: LegalHold | null;
  /** WORM: no one can change or delete it before its retention ends. Evidence bundles are always immutable. */
  immutable: boolean;
  referenceCount: number;
  versionCount: number;
  /** Admins only. */
  storage?: StorageLocation;
  /** How the file was last read (files-service `data`, c-250): null until an extraction is recorded on it. */
  data?: FileData | null;
}

/** "Read as": the document type and version a file was read with, by a template or the model, and what to check. */
export interface FileData {
  /** Null when Detect found no type the file matches: it was read, as nothing the team knows. */
  typeId: string | null;
  /** The type's name when it was read, so a list names it without looking the type up. */
  typeName?: string | null;
  version: number | null;
  path: 'template' | 'model';
  templateId?: string | null;
  fieldsToCheck: number;
  extractionId: string;
  readAt: string;
}

export type FileDataInput = FileData;

/**
 * A request to read a file with a document type (files-service, c-250): it raises the file's read event, which starts
 * the system extract workflow as the person; `runId` is set once the run is started.
 */
export interface ReadRequest {
  key: string;
  fileId: string;
  /** Null for a Detect read, which classifies the file over the team's types. */
  documentTypeId: string | null;
  version: number | null;
  /** `unhandled` when no live workflow takes a file's read event. */
  status: 'queued' | 'started' | 'unhandled';
  runId: string | null;
  requestedBy: string;
  requestedAt: string;
}

export interface ReadRequestInput {
  /** Absent asks Detect to classify the file over the team's types and read it with the one found. */
  documentTypeId?: string;
  version?: number;
  typeName?: string;
  /** `propose`: the model proposes the fields from the first pages, then the file is read with them. Fields when absent. */
  read?: 'fields' | 'propose';
  /** What the document is, to steer a proposal (e.g. "a tax levy notice"). */
  hint?: string;
  /** Read only the first pages. */
  maxPages?: number;
}

/** First page or rows the console can show without downloading the file. Built by the server after scanning. */
export type FilePreview =
  | { kind: 'text'; text: string }
  | { kind: 'csv'; header: string[]; rows: string[][]; totalRows: number }
  | { kind: 'pdf'; pages: number; firstPage: string }
  | { kind: 'image'; width: number; height: number; description: string }
  | { kind: 'none'; reason: string };

export interface FileDetail extends FileRecord {
  /** What the caller may do with it, from the same check its write routes run (c-216); on the detail only. */
  canEdit?: boolean;
  canDelete?: boolean;
  canPublish?: boolean;
  versions: FileVersion[];
  references: FileReference[];
  /** Absent on files-service: audit entries live in the platform audit log. */
  audit?: AuditEntry[];
  /** Absent on files-service, which renders no previews yet. */
  preview?: FilePreview;
  /** Why the file cannot be deleted now, if it cannot. */
  deleteBlockedBy?: string;
}

export type FileView = 'all' | 'quarantined' | 'legal_hold' | 'unreferenced' | 'expiring';
export type FileFilters = {
  purpose?: string[];
  team?: string[];
  sensitivity?: string[];
  scan?: string[];
  retention?: string[];
  /** One ISO timestamp each: the uploaded-at range, inclusive of `uploadedAfter`, exclusive of `uploadedBefore`. */
  uploadedAfter?: string[];
  uploadedBefore?: string[];
};
export type FileViewCounts = Record<FileView, number>;

// ── Upload ──

export interface UploadRequest {
  name: string;
  size: number;
  mime: string;
  purpose: FilePurpose;
  /** Owner group; defaults to the current team. */
  team?: string;
  /** Defaults to the class that applies to the purpose. */
  retentionClass?: string;
  /** sha256 hex computed in the browser; storage rejects bytes that do not match it. */
  digest?: string;
}

/** A presigned PUT (S3) or SAS URL (Azure Blob) for one object key, valid for minutes. */
export interface UploadTicket {
  fileId: string;
  uploadUrl: string;
  method: 'PUT';
  /** Headers the PUT must carry (content type, checksum, blob type); the signature covers them. */
  headers: Record<string, string>;
  expiresAt: string;
}

export interface CompletedUpload {
  file: FileRecord;
  /** Set when identical content already existed in the team: the upload was discarded and this is the stored file. */
  deduplicated: boolean;
}

export interface DownloadLink {
  url: string;
  expiresAt: string;
  ttlSeconds: number;
}

export interface PurposeLimit {
  purpose: FilePurpose;
  /** Extensions without the dot, e.g. pdf. */
  allowedTypes: string[];
  maxSizeMb: number;
}

/** What the upload component enforces before asking for a ticket. The server enforces the same values. */
export interface UploadLimits {
  perPurpose: PurposeLimit[];
  scanning: boolean;
}

export type EvidenceExportInput = { kind: 'model'; entryId: string; version?: number } | { kind: 'publish_request'; reviewId: string };

// ── Storage settings ──

export interface RetentionClass {
  id: string;
  name: string;
  /** null keeps files until deleted by a person. */
  days: number | null;
  purposes: FilePurpose[];
  /** Applies WORM storage: no change or delete until the period ends. */
  worm: boolean;
  /** Deleting before the period ends is refused (a minimum, not only a maximum). */
  keepUntilEnd: boolean;
}

/** Where storage settings send bytes: files-service's development backend, S3 or Azure Blob (no GCS). */
export type StorageBackendName = 'local' | 's3' | 'azure_blob';

/** Where one upload purpose stores its bytes (files-service `/v1/settings/storage`, c-100). `default` covers every
 * purpose without its own target. */
export interface StorageTarget {
  purpose: FilePurpose | 'default';
  backend: StorageBackendName;
  /** Bucket (S3), container (Azure Blob) or folder name (local). */
  container: string;
  region: string;
  /** S3-compatible endpoint, or the Azure storage account URL; empty uses the provider default. */
  endpoint: string;
  /** A storage credential's name; empty on local. */
  credential: string;
  /** direct: the browser sends bytes to storage on a signed URL; proxy: through files-service. */
  uploadPath: 'direct' | 'proxy';
  /** KMS key alias (S3) or encryption scope (Azure Blob). */
  encryption: string;
}

export interface PurposeRetention {
  purpose: FilePurpose;
  retentionClass: string;
}

export interface StorageDocument {
  targets: StorageTarget[];
  limits: PurposeLimit[];
  retention: PurposeRetention[];
  downloadLinkSeconds: number;
}

export interface StorageSettings {
  /** 0 until the first save. */
  version: number;
  updatedBy: string | null;
  updatedAt: string | null;
  document: StorageDocument;
  /** How files are scanned, a deployment setting shown here and never changed (scanning is off for now). */
  scanning: string;
  /** The classes a purpose may take; defined by the deployment. */
  retentionClasses: { id: string; name: string; days: number | null }[];
}

export interface StorageSettingsInput {
  /** The version the change was made from; a newer saved version refuses it with 409. */
  version: number;
  document: StorageDocument;
}

export interface ConnectionTest {
  ok: boolean;
  steps: { label: string; ok: boolean; detail: string }[];
}

export type StorageCredentialKind = 'aws_access_key' | 'azure_service_principal';

/** A named storage credential: never its values, which files-service seals and never returns. */
export interface StorageCredential {
  name: string;
  kind: StorageCredentialKind;
  setBy: string;
  setAt: string;
}

export interface StorageCredentialInput {
  kind: StorageCredentialKind;
  /** aws_access_key: accessKeyId, secretAccessKey; azure_service_principal: tenantId, clientId, clientSecret. */
  values: Record<string, string>;
}

