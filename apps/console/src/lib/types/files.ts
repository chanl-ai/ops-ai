import type { OpsAI } from '@chanl-ai/ops-ai';

import type { AuditEntry } from './governance';

/**
 * Files: every byte the platform stores goes through the Files API. Other APIs take and return a `fileId`,
 * never raw bytes. Bytes travel browser → object storage on a short-lived presigned URL, so the control plane
 * holds metadata only (spec 10).
 */
type Files = OpsAI['raw']['files'];
type Reply<K extends keyof Files> = Awaited<ReturnType<Files[K]>>;
type Body<K extends keyof Files> = NonNullable<NonNullable<Parameters<Files[K]>[0]>['body']>;

// Entity types come from the generated SDK (files-service's OpenAPI document), so a field renamed there fails the console's typecheck.
type ServedDetail = Reply<'files_get_file'>;
/** What files-service accepts as a purpose. The console still names two more (skills and sign-in metadata store files under them); files-service does not know them yet. */
export type FilePurpose = ServedDetail['purpose'] | 'skill_resource' | 'idp_metadata';
export type FileRecord = Omit<Reply<'files_list_files'>['data'][number], 'purpose' | 'sensitivity'> & { purpose: FilePurpose; sensitivity: FileSensitivity };
export type FileScan = NonNullable<ServedDetail['scan']>;
export type ScanStatus = FileScan['status'];
export type FileSensitivity = ServedDetail['sensitivity'];
/** Where the object sits. Returned to platform admins only; everyone else gets `undefined`. */
export type StorageLocation = NonNullable<ServedDetail['storage']>;
export type StorageBackend = StorageLocation['backend'];
export type StorageEnvironment = StorageLocation['environment'];
export type FileRetention = ServedDetail['retention'];
export type LegalHold = NonNullable<ServedDetail['legalHold']>;
/** "Read as": the document type and version a file was read with, by a template or the model, and what to check. */
export type FileData = NonNullable<ServedDetail['data']>;
export type FileDataInput = Body<'files_set_file_data'>;
/** Something that uses the file. Removing a referenced file is refused while any reference exists. */
export type FileReferenceType = NonNullable<ServedDetail['references']>[number]['type'] | 'skill';
export type FileReference = Omit<NonNullable<ServedDetail['references']>[number], 'type'> & { type: FileReferenceType };
export type FileVersion = NonNullable<ServedDetail['versions']>[number];
export type ReadRequest = Reply<'files_get_read_request'>;
export type ReadRequestInput = Body<'files_request_read'>;

/** First page or rows the console can show without downloading the file. Built by the server after scanning. */
export type FilePreview =
  | { kind: 'text'; text: string }
  | { kind: 'csv'; header: string[]; rows: string[][]; totalRows: number }
  | { kind: 'pdf'; pages: number; firstPage: string }
  | { kind: 'image'; width: number; height: number; description: string }
  | { kind: 'none'; reason: string };

/** files-service's detail plus what it does not return yet: audit entries (kept in the platform audit log) and previews. */
export type FileDetail = Omit<ServedDetail, 'purpose' | 'references' | 'scan' | 'versions'> & {
  purpose: FilePurpose;
  // The schema marks fields that have a default as optional; files-service always sends these three.
  scan: FileScan;
  versions: FileVersion[];
  references: FileReference[];
  audit?: AuditEntry[];
  preview?: FilePreview;
};

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

// The schema lists `sensitivity` as required although files-service defaults it to internal.
export type UploadRequest = Omit<Body<'files_create_upload'>, 'purpose' | 'sensitivity'> & { purpose: FilePurpose; sensitivity?: FileSensitivity };
export type UploadTicket = Reply<'files_create_upload'>;
export type CompletedUpload = Omit<Reply<'files_complete_upload'>, 'file'> & { file: FileDetail };
export type DownloadLink = Reply<'files_download_url'>;
export type PurposeLimit = Omit<Reply<'files_upload_limits'>['perPurpose'][number], 'purpose'> & { purpose: FilePurpose };
export type UploadLimits = Omit<Reply<'files_upload_limits'>, 'perPurpose'> & { perPurpose: PurposeLimit[] };

export type EvidenceExportInput = { kind: 'model'; entryId: string; version?: number } | { kind: 'publish_request'; reviewId: string };

// ── Storage settings ──

type ServedStorage = Reply<'settings_get_settings'>;
export type StorageSettings = Omit<ServedStorage, 'document'> & { document: StorageDocument };
// The schema marks the document's defaulted fields optional; files-service always sends all of them.
export type StorageDocument = Omit<Required<ServedStorage['document']>, 'targets' | 'limits' | 'retention'> & {
  targets: StorageTarget[];
  limits: PurposeLimit[];
  retention: PurposeRetention[];
};
type ServedTarget = NonNullable<ServedStorage['document']['targets']>[number];
export type StorageTarget = Omit<ServedTarget, 'purpose'> & { purpose: FilePurpose | 'default' };
export type PurposeRetention = Omit<NonNullable<ServedStorage['document']['retention']>[number], 'purpose'> & { purpose: FilePurpose };
export type StorageBackendName = StorageTarget['backend'];
/** files-service answers an id, a name and the days; the console's mock and settings page also carry the rest, which the API does not return yet. */
export type RetentionClass = ServedStorage['retentionClasses'][number] & { purposes: FilePurpose[]; worm: boolean; keepUntilEnd: boolean };
export type StorageSettingsInput = Omit<Body<'settings_save_settings'>, 'document'> & { document: StorageDocument };
export type ConnectionTest = Reply<'settings_test_target'>;
export type StorageCredential = Reply<'settings_list_credentials'>[number];
export type StorageCredentialKind = StorageCredential['kind'];
export type StorageCredentialInput = Body<'settings_set_credential'>;
