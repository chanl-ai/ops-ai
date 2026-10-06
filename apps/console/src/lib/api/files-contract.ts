import type { BulkResult } from '@/lib/types/domain';
import type {
  CompletedUpload,
  ConnectionTest,
  DownloadLink,
  EvidenceExportInput,
  FileDetail,
  FileFilters,
  FileRecord,
  FileReference,
  FileVersion,
  FileView,
  FileViewCounts,
  StorageEnvironment,
  StorageSettings,
  StorageSettingsInput,
  UploadLimits,
  UploadRequest,
  UploadTicket,
} from '@/lib/types/files';
import type { AuditFilters, AuditView } from '@/lib/types/governance';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * The only API that handles file bytes. Uploads are three calls: `createUpload` returns a presigned URL for one
 * object, `transfer` PUTs the bytes straight to object storage, and `completeUpload` verifies the digest and
 * starts the malware scan. Every other API takes the resulting `fileId`. Downloads are short-lived signed URLs,
 * and each one issued is audited.
 */
export interface FilesApi {
  createUpload(input: UploadRequest): Promise<UploadTicket>;
  /** Direct to storage, never through the control plane. `onProgress` gets 0..1. */
  transfer(ticket: UploadTicket, body: Blob, onProgress?: (fraction: number) => void): Promise<void>;
  /** 409 when the stored bytes do not match `digest`. Identical content in the team returns the stored file instead. */
  completeUpload(fileId: string, input: { digest: string }): Promise<CompletedUpload>;
  get(id: string): Promise<FileDetail>;
  list(params: ListParams<FileFilters> & { view: FileView }): Promise<ListResult<FileRecord> & { viewCounts: FileViewCounts }>;
  /** 423 while the file is quarantined or still being scanned. */
  downloadUrl(id: string): Promise<DownloadLink>;
  versions(id: string): Promise<FileVersion[]>;
  references(id: string): Promise<FileReference[]>;
  /** Immutable files and files under legal hold are skipped with the reason. */
  setRetention(ids: string[], classId: string): Promise<BulkResult>;
  /** `reason` is required to place a hold and to release one. */
  setLegalHold(ids: string[], hold: boolean, reason: string): Promise<BulkResult>;
  /** 409 naming what blocks it: references, legal hold, or retention. */
  remove(id: string): Promise<void>;
  bulkRemove(ids: string[]): Promise<BulkResult>;
  /** Seals the evidence for a model entry version or a publish request into one immutable file. Exporting again returns the same file. */
  exportEvidence(input: EvidenceExportInput): Promise<FileRecord>;
  /** Writes the audit entries in this view to a CSV file. */
  exportAudit(params: ListParams<AuditFilters> & { view: AuditView }): Promise<FileRecord>;
  /** Readable by everyone who can upload. */
  limits(): Promise<UploadLimits>;
  storage: {
    get(): Promise<StorageSettings>;
    /** 409 when someone saved a newer version. Platform admins only. */
    update(input: StorageSettingsInput): Promise<StorageSettings>;
    test(environment: StorageEnvironment): Promise<ConnectionTest>;
  };
}
