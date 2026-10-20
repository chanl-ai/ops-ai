import type { BulkResult } from '@/lib/types/domain';
import type {
  CompletedUpload,
  ConnectionTest,
  DownloadLink,
  EvidenceExportInput,
  FileDataInput,
  FileDetail,
  ReadRequest,
  ReadRequestInput,
  FileFilters,
  FileRecord,
  FileReference,
  FileVersion,
  FileView,
  FileViewCounts,
  StorageCredential,
  StorageCredentialInput,
  StorageSettings,
  StorageSettingsInput,
  StorageTarget,
  UploadLimits,
  UploadRequest,
  UploadTicket,
} from '@/lib/types/files';
import type {
  DocumentType,
  DocumentTypeInput,
  DocumentTypeList,
  DocumentTypeSample,
  DocumentTypeSampleInput,
  DocumentTypeTestEstimate,
  DocumentTypeTestRun,
  DocumentTypeVersion,
  DocumentTypeVersionInput,
} from '@/lib/types/document-types';
import type { Extraction, ExtractionInput } from '@/lib/types/extractions';
import type { AuditFilters, AuditView } from '@/lib/types/governance';
import type { ListParams, ListResult, OptionsPage, OptionsParams } from '@/lib/types/query';

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
  /** Records how the file was read; 403 role_required for a chat-only member, 404 for another team's file. */
  setData(id: string, input: FileDataInput): Promise<FileDetail>;
  /** Reading a file: 202 with the request; a repeat with the same key returns the first. The file must be clean. */
  readRequests: {
    start(fileId: string, input: ReadRequestInput, idempotencyKey: string): Promise<ReadRequest>;
    get(fileId: string, key: string): Promise<ReadRequest>;
  };
  /** The file picker's choices: the team's files by name, one not scanned clean disabled with the reason. */
  options(params: OptionsParams): Promise<OptionsPage>;
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
  /** files-service `/v1/settings/storage` (c-100): admins on the Security team only. */
  storage: {
    get(): Promise<StorageSettings>;
    /** 409 when someone saved a newer version; 422 naming the purpose whose target fails its test, saving nothing. */
    update(input: StorageSettingsInput): Promise<StorageSettings>;
    /** Writes, reads and deletes a small object on the target with its credential; saves nothing. */
    test(target: StorageTarget): Promise<ConnectionTest>;
    credentials: {
      list(): Promise<StorageCredential[]>;
      /** Sets or replaces a credential; its values are never returned. */
      set(name: string, input: StorageCredentialInput): Promise<StorageCredential>;
      /** 409 while a target signs in with it. */
      remove(name: string): Promise<void>;
    };
  };
  /** files-service `/v1/document-types` (c-236): the team's document types, their versions, samples and tests. */
  documentTypes: {
    list(): Promise<DocumentTypeList>;
    get(id: string): Promise<DocumentType>;
    /** 403 when the caller's role cannot change document types; 409 when the id or name is taken. */
    create(input: DocumentTypeInput): Promise<DocumentType>;
    /** Saves version n+1; earlier versions never change. */
    addVersion(id: string, input: DocumentTypeVersionInput): Promise<DocumentTypeVersion>;
    /** `expected` names fields of the newest version; a list of records when that version reads several. */
    addSample(id: string, input: DocumentTypeSampleInput): Promise<DocumentTypeSample>;
    removeSample(id: string, sampleId: string): Promise<void>;
    /** What testing the version spends: one model call per sample, at most `capped` samples. */
    estimate(id: string, version: number): Promise<DocumentTypeTestEstimate>;
    /** Queues a test over the samples; 400 when the type has none. */
    startTest(id: string, version: number): Promise<DocumentTypeTestRun>;
    test(id: string, testId: string): Promise<DocumentTypeTestRun>;
  };
  /** documents-service `/v1/documents/extractions` (c-256): reading a file with a document type. */
  extractions: {
    /** 200 with the answer when it ran now, 202 with its id and status when it runs later; a retry with the same key reads the same extraction. */
    start(input: ExtractionInput, idempotencyKey: string): Promise<Extraction>;
    get(id: string): Promise<Extraction>;
    /** The file's extractions in the caller's team, newest first; 404 when the team cannot see the file. */
    byFile(fileId: string): Promise<ListResult<Extraction>>;
    /** A person's value for one field; the value as read stays beside it. `record` for a read of several records. */
    correct(id: string, key: string, value: unknown, record?: number): Promise<Extraction>;
  };
}
