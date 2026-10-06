import type { AuditEntry } from './governance';

/**
 * Files: every byte the platform stores goes through the Files API. Other APIs take and return a `fileId`,
 * never raw bytes. Bytes travel browser → object storage on a short-lived presigned URL, so the control plane
 * holds metadata only (spec 10).
 */
export type FilePurpose = 'knowledge_source' | 'chat_attachment' | 'case_attachment' | 'test_import' | 'evidence_bundle' | 'export' | 'tool_spec' | 'avatar';
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

export type FileReferenceType = 'source' | 'case' | 'chat' | 'eval_set' | 'test_set' | 'evidence' | 'export' | 'tool_module';

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
}

/** First page or rows the console can show without downloading the file. Built by the server after scanning. */
export type FilePreview =
  | { kind: 'text'; text: string }
  | { kind: 'csv'; header: string[]; rows: string[][]; totalRows: number }
  | { kind: 'pdf'; pages: number; firstPage: string }
  | { kind: 'image'; width: number; height: number; description: string }
  | { kind: 'none'; reason: string };

export interface FileDetail extends FileRecord {
  versions: FileVersion[];
  references: FileReference[];
  audit: AuditEntry[];
  preview: FilePreview;
  /** Why the file cannot be deleted now, if it cannot. */
  deleteBlockedBy?: string;
}

export type FileView = 'all' | 'quarantined' | 'legal_hold' | 'unreferenced' | 'expiring';
export type FileFilters = { purpose?: string[]; team?: string[]; sensitivity?: string[]; scan?: string[]; retention?: string[] };
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

export interface S3Settings {
  bucket: string;
  region: string;
  kmsKeyAlias: string;
  /** Object Lock in compliance mode on the evidence prefix. */
  objectLockEvidence: boolean;
}

export interface AzureBlobSettings {
  account: string;
  container: string;
  encryptionScope: string;
  /** Locked time-based immutability policy on the evidence container. */
  immutabilityPolicy: boolean;
}

export interface StorageTarget {
  environment: StorageEnvironment;
  backend: StorageBackend;
  /** The Integrations connection the platform signs in to storage with. */
  connectionId: string;
  s3?: S3Settings;
  azure?: AzureBlobSettings;
  /** Region the data must stay in. */
  residency: string;
}

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

export interface StorageSettings {
  version: number;
  updatedBy: string;
  updatedAt: string;
  targets: StorageTarget[];
  limits: PurposeLimit[];
  scanning: { enabled: boolean; engine: 'clamav' | 'defender' | 'icap' };
  retentionClasses: RetentionClass[];
  signedUrlMinutes: number;
}

export type StorageSettingsInput = Omit<StorageSettings, 'updatedBy' | 'updatedAt'>;

export interface ConnectionTest {
  ok: boolean;
  at: string;
  steps: { label: string; ok: boolean; detail: string }[];
}
