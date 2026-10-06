import type {
  CompletedUpload,
  ConnectionTest,
  FileDetail,
  FilePreview,
  FilePurpose,
  FileRecord,
  FileReference,
  FileView,
  FileVersion,
  LegalHold,
  ScanStatus,
  StorageSettings,
  StorageTarget,
  UploadRequest,
  UploadTicket,
} from '@/lib/types/files';
import type { AuditEntry } from '@/lib/types/governance';

import { ApiError } from '../../contract';
import type { FilesApi } from '../../files-contract';
import { auditSink } from '../governance';
import { contracts, lendingFiles } from '../knowledge/seed-sources';
import { bulk, field, id, list, mode, notFound, respond } from '../runtime';
import { guardTeam, inTeam, teamDirectory, teamOwner } from '../teams';
import { daysAgo, fileSeeds, PDF_FIRST_PAGE, STORAGE, SUGGESTED } from './seed';

const DAY = 86_400_000;
const SCAN_MS = 1800;
const ENGINE: Record<StorageSettings['scanning']['engine'], string> = { clamav: 'ClamAV 1.4', defender: 'Microsoft Defender for Storage', icap: 'Bank ICAP gateway' };

interface Stored {
  id: string;
  name: string;
  mime: string;
  size: number;
  digest: string;
  purpose: FilePurpose;
  team: string;
  uploadedBy: string;
  uploadedAt: string;
  scan: { status: ScanStatus; engine?: string; at?: string; detail?: string; readyAt?: number; verdict?: 'clean' | 'infected' };
  sensitivity: FileRecord['sensitivity'];
  sensitivitySuggested: boolean;
  retentionClass: string;
  legalHold: LegalHold | null;
  immutable: boolean;
  references: FileReference[];
  versions: FileVersion[];
  content?: string;
  /** Model entry or review the evidence bundle seals, so a second export returns this file. */
  sealKey?: string;
}

interface PendingUpload {
  ticket: UploadTicket;
  input: UploadRequest & { team: string };
  transferred: boolean;
}

const ext = (name: string) => name.split('.').pop()?.toLowerCase() ?? '';
export const mimeOf = (name: string) =>
  ({
    pdf: 'application/pdf',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    docm: 'application/vnd.ms-word.document.macroEnabled.12',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    xlsm: 'application/vnd.ms-excel.sheet.macroEnabled.12',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    csv: 'text/csv',
    txt: 'text/plain',
    md: 'text/markdown',
    html: 'text/html',
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    svg: 'image/svg+xml',
    eml: 'message/rfc822',
    msg: 'application/vnd.ms-outlook',
    zip: 'application/zip',
    json: 'application/json',
    yaml: 'application/yaml',
    yml: 'application/yaml',
  })[ext(name)] ?? 'application/octet-stream';

/** Deterministic stand-in for sha256 so the same seeded content dedupes across cases. */
function fakeDigest(seed: string) {
  let h = 2166136261;
  let out = '';
  for (let round = 0; round < 8; round++) {
    for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i) ^ round, 16777619) >>> 0;
    out += h.toString(16).padStart(8, '0');
  }
  return out;
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const ymd = (iso: string) => iso.slice(0, 10);

export interface FilesDeps {
  me: string;
  /** Model entry name, owner and current version, for evidence exports. */
  modelEntry: (entryId: string) => { name: string; owner: string; version: number } | undefined;
  /** Publish request or validation review, with the team that owns its workflow. */
  review: (reviewId: string) => { id: string; kind: string; workflowName: string; toVersion?: number; owner: string } | undefined;
  /** Rows the audit export would write. */
  auditCount: () => number;
}

/** What other mocks use to attach files to their records. */
export interface FileLinks {
  /** Records `ref` on the file. Refuses files outside the team, of another purpose, quarantined or still scanning. */
  link: (fileId: string, ref: Omit<FileReference, 'addedAt'>, purposes: FilePurpose[]) => FileRecord;
  /** An attachment that arrived by email: stored, scanned and referenced by the case. Identical content in a team is stored once. */
  intake: (a: { name: string; size: number; team: string; ref: Omit<FileReference, 'addedAt'>; infected?: boolean; hold?: Omit<LegalHold, 'at'> }) => FileRecord;
  /** Current state for a referencing record (scan may finish after it was linked). */
  state: (fileId: string) => { scan: ScanStatus; blocked?: string } | undefined;
}

export function createFilesMock(deps: FilesDeps): { api: FilesApi; links: FileLinks } {
  const { me } = deps;
  let settings: StorageSettings = { ...structuredClone(STORAGE), updatedAt: daysAgo(STORAGE.updatedDaysAgo) };
  const classOf = (cid: string) => settings.retentionClasses.find((c) => c.id === cid);
  const defaultClass = (p: FilePurpose) => settings.retentionClasses.find((c) => c.purposes.includes(p))?.id ?? settings.retentionClasses[0].id;
  const isAdmin = () => teamDirectory.current().scope === 'all';
  const prod = (): StorageTarget => settings.targets.find((t) => t.environment === 'prod') ?? settings.targets[0];

  const files: Stored[] = [];
  const pending = new Map<string, PendingUpload>();

  const seedVersions = (digest: string, size: number, by: string, at: string, n: number): FileVersion[] =>
    Array.from({ length: n }, (_, i) => {
      const v = n - i;
      return { version: v, digest: i === 0 ? digest : fakeDigest(`${digest}-v${v}`), size: Math.max(1024, size - i * 2048), uploadedBy: by, uploadedAt: i === 0 ? at : daysAgo((n - v) * 30 + 60), current: i === 0 };
    });

  for (const s of fileSeeds(contracts, lendingFiles)) {
    const at = daysAgo(s.daysAgo);
    const size = s.sizeKb * 1024;
    const digest = fakeDigest(`${s.name}:${size}`);
    const infected = s.scan === 'infected';
    files.push({
      id: s.id,
      name: s.name,
      mime: mimeOf(s.name),
      size,
      digest,
      purpose: s.purpose,
      team: s.team,
      uploadedBy: s.by,
      uploadedAt: at,
      scan:
        s.scan === 'pending'
          ? { status: 'pending', engine: ENGINE.clamav, readyAt: Date.now() + 20_000, verdict: 'clean' }
          : { status: s.scan ?? 'clean', engine: ENGINE.clamav, at, detail: s.scanDetail },
      sensitivity: s.sensitivity ?? SUGGESTED[s.purpose],
      sensitivitySuggested: !s.sensitivity && s.purpose !== 'evidence_bundle' && s.daysAgo < 10,
      retentionClass: defaultClass(s.purpose),
      legalHold: s.hold ? { by: s.hold.by, reason: s.hold.reason, at: daysAgo(s.hold.daysAgo) } : null,
      immutable: s.purpose === 'evidence_bundle',
      references: infected ? [] : (s.refs ?? []).map((r) => ({ ...r, addedAt: at })),
      versions: seedVersions(digest, size, s.by, at, s.versions ?? 1),
      content: s.content,
      sealKey: s.purpose === 'evidence_bundle' ? s.refs?.[0]?.id : undefined,
    });
  }

  // ── Derived ─────────────────────────────────────────────────────────────
  /** Finishes a scan whose time has come; called on every read so state moves without a timer. */
  const settle = (f: Stored) => {
    if (f.scan.status === 'pending' && f.scan.readyAt && Date.now() >= f.scan.readyAt) {
      f.scan = { status: f.scan.verdict ?? 'clean', engine: f.scan.engine, at: new Date().toISOString(), detail: f.scan.verdict === 'infected' ? 'Eicar-Test-Signature' : undefined };
      if (f.scan.status === 'infected') auditLog(f, 'edited', 'Quarantined: the malware scan found Eicar-Test-Signature', [{ field: 'Scan', before: 'Pending', after: 'Infected' }]);
    }
    return f;
  };
  const deleteAfter = (f: Stored) => {
    const c = classOf(f.retentionClass);
    return c?.days == null ? null : ymd(new Date(new Date(f.uploadedAt).getTime() + c.days * DAY).toISOString());
  };
  const blockedText = (f: Stored) =>
    f.scan.status === 'infected' ? `Quarantined: ${f.scan.detail ?? 'malware found'}. The content is not available.` : f.scan.status === 'failed' ? 'Not scanned, so not available. Upload a readable copy.' : undefined;

  const location = (f: Stored) => {
    const t = prod();
    const now = new Date(f.uploadedAt);
    const prefix = f.immutable ? 'evidence' : slug(f.team);
    const key = `${prefix}/${f.purpose}/${now.getUTCFullYear()}/${String(now.getUTCMonth() + 1).padStart(2, '0')}/${f.id}`;
    return t.backend === 's3'
      ? { backend: t.backend, environment: t.environment, container: t.s3!.bucket, key, region: t.s3!.region, encryption: t.s3!.kmsKeyAlias, locked: f.immutable && t.s3!.objectLockEvidence }
      : { backend: t.backend, environment: t.environment, container: t.azure!.container, key, region: t.residency, encryption: t.azure!.encryptionScope, locked: f.immutable && t.azure!.immutabilityPolicy };
  };

  function row(f: Stored): FileRecord {
    settle(f);
    const c = classOf(f.retentionClass);
    return {
      id: f.id,
      name: f.name,
      mime: f.mime,
      size: f.size,
      digest: f.digest,
      purpose: f.purpose,
      team: f.team,
      uploadedBy: f.uploadedBy,
      uploadedAt: f.uploadedAt,
      scan: { status: f.scan.status, engine: f.scan.engine, at: f.scan.at, detail: f.scan.detail },
      sensitivity: f.sensitivity,
      sensitivitySuggested: f.sensitivitySuggested,
      retention: { classId: f.retentionClass, className: c?.name ?? f.retentionClass, deleteAfter: deleteAfter(f) },
      legalHold: f.legalHold,
      immutable: f.immutable,
      referenceCount: f.references.length,
      versionCount: f.versions.length,
      storage: isAdmin() ? location(f) : undefined,
    };
  }

  /** Why the file cannot be deleted now, or undefined. Order: hold, references, retention minimum. */
  const deleteBlock = (f: Stored) => {
    if (f.legalHold) return 'Under legal hold';
    if (f.references.length) return `Used by ${f.references.length === 1 ? f.references[0].name : `${f.references.length} records`}`;
    const c = classOf(f.retentionClass);
    const until = deleteAfter(f);
    if (c?.keepUntilEnd && until && until > ymd(new Date().toISOString())) return f.immutable ? `Immutable until ${until}` : `Kept until ${until} by ${c.name}`;
    return undefined;
  };

  const preview = (f: Stored): FilePreview => {
    if (f.scan.status !== 'clean') return { kind: 'none', reason: f.scan.status === 'pending' ? 'Preview appears once the scan finishes.' : (blockedText(f) ?? 'No preview') };
    const e = ext(f.name);
    if (e === 'csv' && f.content) {
      const [h, ...rows] = f.content.split('\n').map((l) => l.match(/("([^"]|"")*"|[^,]*)(,|$)/g)?.map((c) => c.replace(/,$/, '').replace(/^"|"$/g, '')).filter((_, i, a) => i < a.length - 1) ?? []);
      return { kind: 'csv', header: h, rows: rows.slice(0, 5), totalRows: rows.length };
    }
    if (e === 'csv') return { kind: 'csv', header: ['at', 'actor', 'action', 'target', 'summary'], rows: [['2026-09-08T14:02:11Z', 'Priya Shah', 'published', 'workflow', 'Published Lending servicing inbox v3']], totalRows: Math.round(f.size / 120) };
    if (['txt', 'md', 'yaml', 'yml', 'json', 'html'].includes(e)) return { kind: 'text', text: f.content ?? `${f.name}\n\n(first lines of the document)` };
    if (e === 'pdf') return { kind: 'pdf', pages: Math.max(1, Math.round(f.size / 40_000)), firstPage: PDF_FIRST_PAGE[f.name] ?? `${f.name.replace(/\.pdf$/, '')}\n\nPage 1 of the document as text.` };
    if (['png', 'jpg', 'jpeg', 'svg'].includes(e)) return { kind: 'image', width: 1280, height: 720, description: f.name };
    if (e === 'zip') return { kind: 'text', text: f.content ?? 'manifest.json\ndefinition.json\ntest-results.json\nbaseline-comparison.json\napprovals.json\nreviewer-notes.md\nSHA256SUMS' };
    return { kind: 'none', reason: `No preview for ${e.toUpperCase()} files. Download it to open.` };
  };

  const href = (f: Stored) => `/files?file=${f.id}`;
  function auditLog(f: Stored, action: AuditEntry['action'], summary: string, diff: AuditEntry['diff'] = [], reason?: string) {
    auditSink.log({ action, target: { type: 'file', name: f.name, href: href(f) }, summary, diff, reason, owner: f.team === 'Platform' ? undefined : f.team });
  }

  function detail(f: Stored): FileDetail {
    const r = row(f);
    const team = teamDirectory.ofOwner(f.team);
    const uploaded: AuditEntry = {
      id: `aud_${f.id}_up`,
      at: f.uploadedAt,
      actor: f.uploadedBy === 'Mailbox intake' || f.uploadedBy === 'Eval runner' ? { kind: 'workflow', name: f.uploadedBy, detail: `svc-${slug(f.uploadedBy)}` } : { kind: 'person', name: f.uploadedBy, detail: `${slug(f.uploadedBy).replace('-', '.')}@northfield.example` },
      action: f.purpose === 'evidence_bundle' || f.purpose === 'export' ? 'created' : 'uploaded',
      target: { type: 'file', name: f.name, href: href(f) },
      teamId: team.id,
      team: team.name,
      summary: f.purpose === 'evidence_bundle' ? 'Sealed the evidence bundle' : f.purpose === 'export' ? 'Exported' : 'Uploaded',
      diff: [{ field: 'Digest', after: `sha256:${f.digest.slice(0, 12)}…` }],
      requestId: `req_${f.id}`,
    };
    const live = auditSink.entries().filter((e) => e.target.href === href(f));
    const blocked = blockedText(f);
    return {
      ...r,
      versions: f.versions,
      references: f.references.map((x) => (blocked ? { ...x, blocked } : x)),
      audit: [...live, uploaded].sort((a, b) => b.at.localeCompare(a.at)),
      preview: preview(f),
      deleteBlockedBy: deleteBlock(f),
    };
  }

  const visible = () => files.filter((f) => inTeam(f.team));
  const find = (fid: string) => {
    const f = files.find((x) => x.id === fid) ?? notFound('File');
    guardTeam(f.team, 'file');
    return settle(f);
  };

  const inView = (f: FileRecord, v: FileView) => {
    const soon = ymd(new Date(Date.now() + 30 * DAY).toISOString());
    return v === 'all'
      ? true
      : v === 'quarantined'
        ? f.scan.status === 'infected' || f.scan.status === 'failed'
        : v === 'legal_hold'
          ? !!f.legalHold
          : v === 'unreferenced'
            ? f.referenceCount === 0 && Date.now() - new Date(f.uploadedAt).getTime() > 30 * DAY
            : !f.legalHold && !!f.retention.deleteAfter && f.retention.deleteAfter <= soon;
  };

  const limitFor = (p: FilePurpose) => settings.limits.find((l) => l.purpose === p);

  const makeFile = (input: { name: string; size: number; purpose: FilePurpose; team: string; by: string; digest: string; retentionClass?: string; immutable?: boolean; content?: string; scanned?: 'clean' | 'infected' | 'pending' }): Stored => {
    const at = new Date().toISOString();
    const verdict = /eicar/i.test(input.name) || input.scanned === 'infected' ? 'infected' : 'clean';
    const scanOn = settings.scanning.enabled;
    return {
      id: id('file'),
      name: input.name,
      mime: mimeOf(input.name),
      size: input.size,
      digest: input.digest,
      purpose: input.purpose,
      team: input.team,
      uploadedBy: input.by,
      uploadedAt: at,
      scan:
        !scanOn
          ? { status: 'clean', engine: 'Scanning off', at }
          : input.scanned === 'pending' || (!input.scanned && input.purpose !== 'evidence_bundle' && input.purpose !== 'export')
            ? { status: 'pending', engine: ENGINE[settings.scanning.engine], readyAt: Date.now() + SCAN_MS, verdict }
            : { status: verdict, engine: ENGINE[settings.scanning.engine], at, detail: verdict === 'infected' ? 'Eicar-Test-Signature' : undefined },
      sensitivity: SUGGESTED[input.purpose],
      sensitivitySuggested: input.purpose !== 'evidence_bundle',
      retentionClass: input.retentionClass ?? defaultClass(input.purpose),
      legalHold: null,
      immutable: !!input.immutable,
      references: [],
      versions: [{ version: 1, digest: input.digest, size: input.size, uploadedBy: input.by, uploadedAt: at, current: true }],
      content: input.content,
    };
  };

  const uploadUrl = (fileId: string, team: string, purpose: FilePurpose, minutes: number) => {
    const t = prod();
    const now = new Date();
    const key = `${slug(team)}/${purpose}/${now.getUTCFullYear()}/${String(now.getUTCMonth() + 1).padStart(2, '0')}/${fileId}`;
    const sig = fakeDigest(`${fileId}${now.getTime()}`).slice(0, 64);
    return t.backend === 's3'
      ? `https://${t.s3!.bucket}.s3.${t.s3!.region}.amazonaws.com/${key}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=${minutes * 60}&X-Amz-SignedHeaders=content-type%3Bx-amz-checksum-sha256&X-Amz-Signature=${sig}`
      : `https://${t.azure!.account}.blob.core.windows.net/${t.azure!.container}/${key}?sv=2025-05-05&sp=cw&se=${encodeURIComponent(new Date(Date.now() + minutes * 60_000).toISOString())}&sig=${sig}`;
  };

  const api: FilesApi = {
    createUpload: (input) =>
      respond(() => {
        const name = input.name.trim();
        if (!name) throw new ApiError('The file has no name.', 400);
        const lim = limitFor(input.purpose) ?? notFound('Upload purpose');
        if (!lim.allowedTypes.includes(ext(name))) throw new ApiError(`${ext(name).toUpperCase() || 'This type'} is not accepted here. Accepted: ${lim.allowedTypes.map((t) => t.toUpperCase()).join(', ')}.`, 415);
        if (input.size <= 0) throw new ApiError(`${name} is empty.`, 400);
        if (input.size > lim.maxSizeMb * 1024 * 1024) throw new ApiError(`${name} is over the ${lim.maxSizeMb} MB limit.`, 413);
        const team = input.team ?? teamOwner() ?? 'Platform';
        guardTeam(team === 'Platform' ? undefined : team, 'team');
        if (input.retentionClass && !classOf(input.retentionClass)) throw new ApiError('Unknown retention class.', 400);
        const fileId = id('file');
        const t = prod();
        const ticket: UploadTicket = {
          fileId,
          uploadUrl: uploadUrl(fileId, team, input.purpose, 15),
          method: 'PUT',
          headers:
            t.backend === 's3'
              ? { 'Content-Type': input.mime || mimeOf(name), 'x-amz-checksum-sha256': input.digest ?? '', 'x-amz-server-side-encryption': 'aws:kms', 'x-amz-server-side-encryption-aws-kms-key-id': t.s3!.kmsKeyAlias }
              : { 'Content-Type': input.mime || mimeOf(name), 'x-ms-blob-type': 'BlockBlob', 'x-ms-encryption-scope': t.azure!.encryptionScope },
          expiresAt: new Date(Date.now() + 15 * 60_000).toISOString(),
        };
        pending.set(fileId, { ticket, input: { ...input, name, team }, transferred: false });
        return ticket;
      }),

    // Stands in for the PUT to storage: progress in steps, then the object exists. `?mock=error` fails it.
    transfer: (ticket, body, onProgress) =>
      new Promise<void>((resolve, reject) => {
        const p = pending.get(ticket.fileId);
        if (!p) return reject(new ApiError('This upload link is not valid. Start the upload again.', 403));
        if (new Date(ticket.expiresAt).getTime() < Date.now()) return reject(new ApiError('The upload link expired. Start the upload again.', 403));
        const steps = Math.min(20, Math.max(6, Math.round(body.size / 200_000)));
        let k = 0;
        const tick = () => {
          k++;
          onProgress?.(k / steps);
          if (k < steps) return void setTimeout(tick, 90);
          if (mode() === 'error') return reject(new ApiError('Storage did not accept the upload. Try again.', 503));
          p.transferred = true;
          resolve();
        };
        setTimeout(tick, 90);
      }),

    completeUpload: (fileId, { digest }) =>
      respond((): CompletedUpload => {
        const p = pending.get(fileId) ?? notFound('Upload');
        if (!p.transferred) throw new ApiError('The bytes have not reached storage yet.', 409);
        if (p.input.digest && p.input.digest !== digest) throw new ApiError('The stored bytes do not match the file you chose. Upload it again.', 409);
        pending.delete(fileId);
        const same = files.find((f) => f.team === p.input.team && f.digest === digest && f.scan.status !== 'infected');
        if (same) return { file: row(same), deduplicated: true };
        const f = makeFile({ name: p.input.name, size: p.input.size, purpose: p.input.purpose, team: p.input.team, by: me, digest, retentionClass: p.input.retentionClass });
        f.id = fileId;
        files.unshift(f);
        auditLog(f, 'uploaded', `Uploaded ${f.name}`, [
          { field: 'Purpose', after: f.purpose },
          { field: 'Digest', after: `sha256:${digest.slice(0, 12)}…` },
        ]);
        return { file: row(f), deduplicated: false };
      }),

    get: (fid) => respond(() => detail(find(fid))),

    list: (p) =>
      respond((m) => {
        const rows = visible().map(row);
        const src = m === 'empty' ? [] : rows;
        const views: FileView[] = ['all', 'quarantined', 'legal_hold', 'unreferenced', 'expiring'];
        const viewCounts = Object.fromEntries(views.map((v) => [v, src.filter((r) => inView(r, v)).length])) as Record<FileView, number>;
        return {
          ...list(
            rows.filter((r) => inView(r, p.view)).sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt)),
            p,
            { text: (r) => `${r.name} ${r.uploadedBy} ${r.team} ${r.digest}`, value: (r, k) => (k === 'scan' ? r.scan.status : k === 'retention' ? r.retention.classId : field(r, k)), facetKeys: ['purpose', 'team', 'sensitivity', 'scan', 'retention'] },
            m,
          ),
          viewCounts,
        };
      }),

    downloadUrl: (fid) =>
      respond(() => {
        const f = find(fid);
        if (f.scan.status === 'pending') throw new ApiError('Still being scanned. Download is available once the scan finishes.', 423);
        const blocked = blockedText(f);
        if (blocked) throw new ApiError(blocked, 423);
        const ttlSeconds = settings.signedUrlMinutes * 60;
        auditLog(f, 'downloaded', `Issued a download link valid for ${settings.signedUrlMinutes} minutes`);
        // The mock serves the preview text from a local object URL so the link opens; the real one is a presigned GET.
        const p = preview(f);
        const body = p.kind === 'text' ? p.text : p.kind === 'pdf' ? p.firstPage : p.kind === 'csv' ? [p.header, ...p.rows].map((r) => r.join(',')).join('\n') : f.name;
        const url = typeof URL.createObjectURL === 'function' ? URL.createObjectURL(new Blob([body], { type: 'text/plain' })) : uploadUrl(f.id, f.team, f.purpose, settings.signedUrlMinutes);
        return { url, ttlSeconds, expiresAt: new Date(Date.now() + ttlSeconds * 1000).toISOString() };
      }),

    versions: (fid) => respond(() => find(fid).versions),
    references: (fid) => respond(() => detail(find(fid)).references),

    setRetention: (ids, classId) =>
      respond(() => {
        const c = classOf(classId) ?? notFound('Retention class');
        return bulk(ids, (fid) => {
          const f = files.find((x) => x.id === fid);
          if (!f || !inTeam(f.team)) return 'Not found';
          if (f.immutable) return 'Immutable evidence keeps its retention';
          if (f.legalHold) return 'Under legal hold';
          if (!c.purposes.includes(f.purpose)) return `${c.name} does not apply to this kind of file`;
          if (f.retentionClass === classId) return 'Already in that class';
          // Retention only gets longer or stricter, so a change can never shorten what an earlier class promised.
          const cur = classOf(f.retentionClass);
          const longer = (c.days ?? Infinity) >= (cur?.days ?? Infinity);
          if (!longer || (cur?.keepUntilEnd && !c.keepUntilEnd) || (cur?.worm && !c.worm)) return 'Retention can only be made longer or stricter';
          const before = cur?.name;
          f.retentionClass = classId;
          auditLog(f, 'edited', `Retention set to ${c.name}`, [{ field: 'Retention', before, after: c.name }]);
        });
      }),

    setLegalHold: (ids, hold, reason) =>
      respond(() => {
        if (!reason.trim()) throw new ApiError(hold ? 'Give the matter or reason for the hold.' : 'Say why the hold is released.', 400);
        if (!isAdmin()) throw new ApiError('Legal holds are placed and released by Platform admins for Legal.', 403);
        return bulk(ids, (fid) => {
          const f = files.find((x) => x.id === fid);
          if (!f || !inTeam(f.team)) return 'Not found';
          if (hold && f.legalHold) return 'Already under legal hold';
          if (!hold && !f.legalHold) return 'Not under legal hold';
          f.legalHold = hold ? { by: me, at: new Date().toISOString(), reason: reason.trim() } : null;
          auditLog(f, 'legal_hold', hold ? 'Placed a legal hold' : 'Released the legal hold', [{ field: 'Legal hold', before: hold ? 'None' : 'On', after: hold ? 'On' : 'None' }], reason.trim());
        });
      }),

    remove: (fid) =>
      respond(() => {
        const f = find(fid);
        const block = deleteBlock(f);
        if (block) throw new ApiError(`${f.name} can’t be deleted: ${block.charAt(0).toLowerCase()}${block.slice(1)}.`, 409);
        files.splice(files.indexOf(f), 1);
        auditLog(f, 'deleted', `Deleted ${f.name} and every version`, [{ field: 'Versions', before: String(f.versions.length), after: '0' }]);
      }),

    bulkRemove: (ids) =>
      respond(() =>
        bulk(ids, (fid) => {
          const f = files.find((x) => x.id === fid);
          if (!f || !inTeam(f.team)) return 'Not found';
          const block = deleteBlock(settle(f));
          if (block) return block.startsWith('Used by') ? 'Still used by a source, case, chat or test set' : block.startsWith('Kept until') || block.startsWith('Immutable') ? 'Inside its retention period' : block;
          files.splice(files.indexOf(f), 1);
          auditLog(f, 'deleted', `Deleted ${f.name} and every version`);
        }),
      ),

    exportEvidence: (input) =>
      respond(() => {
        let key: string;
        let name: string;
        let owner: string;
        let ref: Omit<FileReference, 'addedAt'>;
        if (input.kind === 'model') {
          const e = deps.modelEntry(input.entryId) ?? notFound('Model');
          const v = input.version ?? e.version;
          key = `${input.entryId}@${v}`;
          name = `evidence-${slug(e.name)}-v${v}.zip`;
          owner = e.owner;
          ref = { type: 'evidence', id: input.entryId, name: `${e.name} v${v}`, href: `/model-risk/${input.entryId}` };
        } else {
          const r = deps.review(input.reviewId) ?? notFound('Publish request');
          if (r.kind !== 'publish_request' && r.kind !== 'model_validation') throw new ApiError('Only publish requests and validations have evidence bundles.', 400);
          key = r.id;
          const v = r.toVersion;
          name = `evidence-${slug(r.workflowName)}${v ? `-v${v}` : ''}-${r.id}.zip`;
          owner = r.owner;
          ref = { type: 'evidence', id: r.id, name: `${r.workflowName}${v ? ` v${v}` : ''} · ${r.kind === 'publish_request' ? 'publish request' : 'validation'}`, href: `/reviews?review=${r.id}` };
        }
        guardTeam(owner, 'model');
        const existing = files.find((f) => f.sealKey === key);
        if (existing) return row(existing);
        const digest = fakeDigest(`${key}:${Date.now()}`);
        const f = makeFile({ name, size: 2_400_000 + Math.round(Math.random() * 900_000), purpose: 'evidence_bundle', team: owner, by: me, digest, immutable: true, scanned: 'clean' });
        f.sealKey = key;
        f.sensitivitySuggested = false;
        f.references.push({ ...ref, addedAt: f.uploadedAt });
        files.unshift(f);
        const lock = prod();
        auditLog(f, 'created', 'Sealed the evidence bundle as an immutable file', [
          { field: 'Retention', after: classOf(f.retentionClass)?.name },
          { field: 'Lock', after: lock.backend === 's3' ? 'S3 Object Lock, compliance mode' : 'Azure immutability policy, locked' },
        ]);
        return row(f);
      }),

    exportAudit: () =>
      respond(() => {
        const n = deps.auditCount();
        if (!n) throw new ApiError('No audit entries in this view to export.', 400);
        const at = new Date().toISOString();
        const f = makeFile({ name: `audit-log-${ymd(at)}.csv`, size: n * 180, purpose: 'export', team: teamOwner() ?? 'Platform', by: me, digest: fakeDigest(`audit:${at}`), scanned: 'clean', content: `at,actor,action,target,summary\n${at},${me},exported,audit,Exported ${n} entries` });
        files.unshift(f);
        auditLog(f, 'created', `Exported ${n} audit entries`);
        return row(f);
      }),

    limits: () => respond(() => ({ perPurpose: settings.limits, scanning: settings.scanning.enabled })),

    storage: {
      get: () => respond(() => settings),
      update: (input) =>
        respond(() => {
          if (!isAdmin()) throw new ApiError('Storage is set by Platform admins.', 403);
          if (input.version !== settings.version) throw new ApiError(`${settings.updatedBy} saved version ${settings.version} after you opened this page. Reload to see it, then make your change again.`, 409);
          if (input.signedUrlMinutes < 1 || input.signedUrlMinutes > 60) throw new ApiError('Signed link lifetime is 1 to 60 minutes.', 400);
          for (const l of input.limits) if (l.maxSizeMb < 1 || l.maxSizeMb > 5120) throw new ApiError('Size limits are 1 to 5,120 MB.', 400);
          const names = input.retentionClasses.map((c) => c.name.trim().toLowerCase());
          if (names.some((n) => !n)) throw new ApiError('Name every retention class.', 400);
          if (new Set(names).size !== names.length) throw new ApiError('Retention class names must be different.', 400);
          for (const c of input.retentionClasses) if (c.days != null && (c.days < 1 || c.days > 36_500)) throw new ApiError(`${c.name}: duration is 1 to 36,500 days, or keep until deleted.`, 400);
          const evidence = input.retentionClasses.find((c) => c.purposes.includes('evidence_bundle'));
          if (!evidence?.worm) throw new ApiError('Evidence bundles need a WORM retention class.', 400);
          for (const t of input.targets) {
            if (t.backend === 's3' && (!t.s3 || !/^[a-z0-9][a-z0-9.-]{2,62}$/.test(t.s3.bucket))) throw new ApiError(`${t.environment}: bucket names are 3 to 63 lowercase letters, digits, dots or hyphens.`, 400);
            if (t.backend === 's3' && !t.s3!.kmsKeyAlias.startsWith('alias/')) throw new ApiError(`${t.environment}: use a KMS key alias, e.g. alias/opsai-prod-files.`, 400);
            if (t.backend === 'azure_blob' && (!t.azure?.account || !t.azure.container)) throw new ApiError(`${t.environment}: add the storage account and container.`, 400);
            if (t.environment === 'prod' && (t.backend === 's3' ? !t.s3!.objectLockEvidence : !t.azure!.immutabilityPolicy)) throw new ApiError('Production evidence must sit under Object Lock or a locked immutability policy.', 400);
          }
          const before = settings;
          settings = { ...structuredClone(input), version: settings.version + 1, updatedBy: me, updatedAt: new Date().toISOString() };
          auditSink.log({ action: 'edited', target: { type: 'storage', name: 'Storage settings', href: '/settings/storage' }, summary: `Saved storage settings as version ${settings.version}`, diff: [{ field: 'Signed link lifetime', before: `${before.signedUrlMinutes} min`, after: `${settings.signedUrlMinutes} min` }] });
          return settings;
        }),
      test: (env) =>
        respond((): ConnectionTest => {
          const t = settings.targets.find((x) => x.environment === env) ?? notFound('Environment');
          const s3 = t.backend === 's3';
          const lock = s3 ? !!t.s3?.objectLockEvidence : !!t.azure?.immutabilityPolicy;
          const steps = [
            { label: 'Signed in', ok: true, detail: s3 ? 'Assumed role opsai-files through the connection' : 'Service principal token issued' },
            { label: 'Wrote, read and deleted a probe object', ok: true, detail: s3 ? `s3://${t.s3!.bucket}/_probe` : `${t.azure!.account}/${t.azure!.container}/_probe` },
            { label: 'Encryption', ok: true, detail: s3 ? `SSE-KMS with ${t.s3!.kmsKeyAlias}` : `Encryption scope ${t.azure!.encryptionScope}` },
            { label: s3 ? 'Object Lock on evidence/' : 'Immutability policy on evidence', ok: lock, detail: lock ? 'Compliance mode; a probe delete was refused' : 'Off: evidence written here could be changed or deleted' },
          ];
          return { ok: steps.every((s) => s.ok), at: new Date().toISOString(), steps };
        }),
    },
  };

  const links: FileLinks = {
    link: (fid, ref, purposes) => {
      const f = files.find((x) => x.id === fid) ?? notFound('File');
      settle(f);
      if (!inTeam(f.team)) throw new ApiError(`${f.name} belongs to another team.`, 403);
      if (!purposes.includes(f.purpose)) throw new ApiError(`${f.name} was uploaded for something else; upload it here again.`, 400);
      if (f.scan.status === 'pending') throw new ApiError(`${f.name} is still being scanned.`, 409);
      const blocked = blockedText(f);
      if (blocked) throw new ApiError(`${f.name}: ${blocked}`, 409);
      if (!f.references.some((r) => r.type === ref.type && r.id === ref.id)) f.references.push({ ...ref, addedAt: new Date().toISOString() });
      return row(f);
    },
    intake: (a) => {
      // Each customer's attachment is its own content; a forwarded duplicate within one case dedupes.
      const digest = fakeDigest(`${a.name}:${a.size}:${a.ref.id}`);
      let f = files.find((x) => x.team === a.team && x.digest === digest);
      if (!f) {
        f = makeFile({ name: a.name, size: a.size, purpose: 'case_attachment', team: a.team, by: 'Mailbox intake', digest, scanned: a.infected ? 'infected' : 'clean' });
        f.uploadedAt = daysAgo(2 + (files.length % 9));
        f.versions[0].uploadedAt = f.uploadedAt;
        f.scan.at = f.uploadedAt;
        f.sensitivitySuggested = false;
        if (a.hold) f.legalHold = { ...a.hold, at: daysAgo(1) };
        files.push(f);
      }
      if (!f.references.some((r) => r.id === a.ref.id)) f.references.push({ ...a.ref, addedAt: f.uploadedAt });
      return row(f);
    },
    state: (fid) => {
      const f = files.find((x) => x.id === fid);
      return f && { scan: settle(f).scan.status, blocked: blockedText(f) };
    },
  };

  return { api, links };
}
