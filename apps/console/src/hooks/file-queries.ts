'use client';

import * as React from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { EvidenceExportInput, FileFilters, FilePurpose, FileView, ScanStatus, StorageEnvironment, StorageSettingsInput } from '@/lib/types/files';
import type { AuditFilters, AuditView } from '@/lib/types/governance';
import type { ListParams } from '@/lib/types/query';

export const fk = {
  list: (p: unknown) => ['files', 'list', p] as const,
  one: (id: string) => ['files', 'one', id] as const,
  limits: ['files', 'limits'] as const,
  storage: ['files', 'storage'] as const,
};

export const useFiles = (p: ListParams<FileFilters> & { view: FileView }) => useQuery({ queryKey: fk.list(p), queryFn: () => api.files.list(p), placeholderData: keepPreviousData });
/** Polls while a scan is running so the sheet moves from Scanning to its result without a reload. */
export const useFile = (id: string | null) =>
  useQuery({ queryKey: fk.one(id ?? ''), queryFn: () => api.files.get(id!), enabled: !!id, refetchInterval: (q) => (q.state.data?.scan.status === 'pending' ? 1000 : false) });
export const useUploadLimits = () => useQuery({ queryKey: fk.limits, queryFn: api.files.limits, staleTime: 60_000 });
export const useStorageSettings = () => useQuery({ queryKey: fk.storage, queryFn: api.files.storage.get });

/** File writes show on the Files page, on whatever references the file, and in the audit log. */
function useFileWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['files', 'logs'].map((k) => qc.invalidateQueries({ queryKey: [k] }))) });
}

/** Asks for a short-lived signed link; each one issued is audited. */
export const useDownloadFile = () => useFileWrite((id: string) => api.files.downloadUrl(id));
export const useSetRetention = () => useFileWrite(({ ids, classId }: { ids: string[]; classId: string }) => api.files.setRetention(ids, classId));
export const useSetLegalHold = () => useFileWrite(({ ids, hold, reason }: { ids: string[]; hold: boolean; reason: string }) => api.files.setLegalHold(ids, hold, reason));
export const useRemoveFiles = () => useFileWrite((ids: string[]) => api.files.bulkRemove(ids));
export const useExportEvidence = () => useFileWrite((i: EvidenceExportInput) => api.files.exportEvidence(i));
export const useExportAudit = () => useFileWrite((p: ListParams<AuditFilters> & { view: AuditView }) => api.files.exportAudit(p));
export const useSaveStorage = () => useFileWrite((i: StorageSettingsInput) => api.files.storage.update(i));
export const useTestStorage = () => useMutation({ mutationFn: (env: StorageEnvironment) => api.files.storage.test(env) });

// ── Upload ──────────────────────────────────────────────────────────────────

export type UploadPhase = 'hashing' | 'uploading' | 'scanning' | 'ready' | 'blocked' | 'error';

export interface UploadItem {
  key: string;
  name: string;
  size: number;
  phase: UploadPhase;
  /** 0..1 while uploading. */
  progress: number;
  fileId?: string;
  scan?: ScanStatus;
  /** Set when the content was already stored in the team; the existing file is reused. */
  deduplicated?: boolean;
  error?: string;
  /** False when retrying cannot help (wrong type, too large). */
  retryable?: boolean;
}

const ext = (name: string) => name.split('.').pop()?.toLowerCase() ?? '';
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** sha256 of the bytes, hex. Storage checks the PUT against it, so a corrupted transfer is refused. */
async function sha256(file: Blob & { name?: string; lastModified?: number }) {
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, '0')).join('');
  }
  // Insecure origins have no SubtleCrypto; the server computes the digest on completion instead.
  return `unverified-${file.name}-${file.size}-${file.lastModified ?? 0}`;
}

/**
 * The upload pipeline every upload in the console uses: check the purpose's limits, hash, ask the Files API for a
 * presigned URL, PUT straight to storage with progress, complete, then wait for the malware scan. Only
 * `components/shared/file-upload.tsx` calls it.
 */
export function useFileUpload({ purpose, team, retentionClass, multiple }: { purpose: FilePurpose; team?: string; retentionClass?: string; multiple: boolean }) {
  const qc = useQueryClient();
  const limits = useUploadLimits();
  const limit = limits.data?.perPurpose.find((l) => l.purpose === purpose);
  const [items, setItems] = React.useState<UploadItem[]>([]);
  const sources = React.useRef(new Map<string, File>());
  const alive = React.useRef(true);
  React.useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const patch = React.useCallback((key: string, p: Partial<UploadItem>) => {
    if (alive.current) setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x)));
  }, []);

  const run = React.useCallback(
    async (key: string, file: File) => {
      try {
        patch(key, { phase: 'hashing', progress: 0, error: undefined });
        const digest = await sha256(file);
        patch(key, { phase: 'uploading' });
        const ticket = await api.files.createUpload({ name: file.name, size: file.size, mime: file.type, purpose, team, retentionClass, digest });
        await api.files.transfer(ticket, file, (f) => patch(key, { progress: f }));
        const done = await api.files.completeUpload(ticket.fileId, { digest });
        let f = done.file;
        patch(key, { phase: f.scan.status === 'pending' ? 'scanning' : 'ready', progress: 1, fileId: f.id, deduplicated: done.deduplicated, scan: f.scan.status });
        while (f.scan.status === 'pending' && alive.current) {
          await sleep(600);
          f = await api.files.get(f.id);
        }
        const ok = f.scan.status === 'clean';
        patch(key, { phase: ok ? 'ready' : 'blocked', scan: f.scan.status, error: ok ? undefined : f.scan.status === 'infected' ? `Quarantined: ${f.scan.detail ?? 'malware found'}` : (f.scan.detail ?? 'The scan could not read the file') });
        qc.invalidateQueries({ queryKey: ['files'] });
      } catch (e) {
        const status = (e as { status?: number }).status ?? 0;
        patch(key, { phase: 'error', error: (e as Error).message, retryable: ![400, 413, 415].includes(status) });
      }
    },
    [patch, purpose, team, retentionClass, qc],
  );

  const add = React.useCallback(
    (picked: File[]) => {
      const next: UploadItem[] = [];
      for (const file of multiple ? picked : picked.slice(0, 1)) {
        const key = `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 6)}`;
        const typeOk = !limit || limit.allowedTypes.includes(ext(file.name));
        const sizeOk = !limit || file.size <= limit.maxSizeMb * 1024 * 1024;
        const error = !typeOk ? `${ext(file.name).toUpperCase() || 'This type'} is not accepted here` : !sizeOk ? `Over the ${limit!.maxSizeMb} MB limit` : file.size === 0 ? 'The file is empty' : undefined;
        next.push({ key, name: file.name, size: file.size, phase: error ? 'error' : 'hashing', progress: 0, error, retryable: !error });
        if (!error) sources.current.set(key, file);
      }
      setItems((xs) => (multiple ? [...xs, ...next] : next));
      for (const it of next) if (it.phase !== 'error') void run(it.key, sources.current.get(it.key)!);
    },
    [limit, multiple, run],
  );

  const remove = React.useCallback((key: string) => {
    sources.current.delete(key);
    setItems((xs) => xs.filter((x) => x.key !== key));
  }, []);
  const retry = React.useCallback(
    (key: string) => {
      const f = sources.current.get(key);
      if (f) void run(key, f);
    },
    [run],
  );
  const reset = React.useCallback(() => {
    sources.current.clear();
    setItems([]);
  }, []);

  return { items, add, remove, retry, reset, limit, limitsLoading: limits.isPending, scanning: limits.data?.scanning ?? true };
}
