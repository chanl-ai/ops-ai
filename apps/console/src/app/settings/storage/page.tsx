'use client';

import * as React from 'react';
import { AlertCircle, CheckCircle2, Info, Lock, Plus, RotateCcw, Trash2, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { PURPOSE_LABEL } from '@/components/files/file-meta';
import { ConnectionChip } from '@/components/integrations/integration-meta';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useSaveStorage, useStorageSettings, useTestStorage } from '@/hooks/file-queries';
import { useIntegrationOptions } from '@/hooks/integration-queries';
import { useTeam } from '@/hooks/use-team';
import { relativeTime } from '@/lib/format';
import type { ConnectionTest, FilePurpose, StorageBackend, StorageEnvironment, StorageSettings, StorageSettingsInput, StorageTarget } from '@/lib/types/files';

const ENV_LABEL: Record<StorageEnvironment, string> = { dev: 'Development', test: 'Test', prod: 'Production' };
const PURPOSES = Object.keys(PURPOSE_LABEL) as FilePurpose[];
const toDraft = (s: StorageSettings): StorageSettingsInput => ({ version: s.version, targets: s.targets, limits: s.limits, scanning: s.scanning, retentionClasses: s.retentionClasses, signedUrlMinutes: s.signedUrlMinutes });

function TestResult({ result }: { result: ConnectionTest }) {
  return (
    <ul className="flex flex-col gap-1 rounded-md border bg-muted/30 px-3 py-2 text-xs" data-testid="storage-test-result">
      {result.steps.map((s) => (
        <li key={s.label} className="flex items-start gap-2">
          {s.ok ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" />}
          <span>
            <span className="font-medium">{s.label}</span> · <span className="text-muted-foreground">{s.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function TargetForm({ t, onChange, disabled, onTest, testing, result }: { t: StorageTarget; onChange: (t: StorageTarget) => void; disabled: boolean; onTest: () => void; testing: boolean; result?: ConnectionTest }) {
  const conns = useIntegrationOptions();
  const kind = t.backend === 's3' ? 'aws_s3' : 'azure_blob';
  const options = (conns.data ?? []).filter((c) => c.kind === kind);
  const conn = options.find((c) => c.id === t.connectionId);
  const p = `st-${t.environment}`;
  const setBackend = (b: StorageBackend) =>
    onChange(
      b === 's3'
        ? { ...t, backend: b, connectionId: '', azure: undefined, s3: t.s3 ?? { bucket: '', region: 'ca-central-1', kmsKeyAlias: 'alias/', objectLockEvidence: true } }
        : { ...t, backend: b, connectionId: '', s3: undefined, azure: t.azure ?? { account: '', container: 'files', encryptionScope: '', immutabilityPolicy: true } },
    );
  return (
    <Section
      title={ENV_LABEL[t.environment]}
      description={`Data stays in ${t.residency}`}
      actions={
        <LoadingButton size="sm" variant="outline" isLoading={testing} onClick={onTest}>
          Test connection
        </LoadingButton>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id={`${p}-backend`} label="Backend">
          <Select value={t.backend} onValueChange={(v) => setBackend(v as StorageBackend)} disabled={disabled}>
            <SelectTrigger id={`${p}-backend`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="s3">Amazon S3 or S3-compatible</SelectItem>
              <SelectItem value="azure_blob">Azure Blob Storage</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
        <FormField id={`${p}-conn`} label="Connection" hint="Signs in to storage. Managed in Integrations.">
          <Select value={t.connectionId} onValueChange={(v) => onChange({ ...t, connectionId: v })} disabled={disabled}>
            <SelectTrigger id={`${p}-conn`} className="w-full">
              <SelectValue placeholder={options.length ? 'Choose a connection' : 'No connection of this kind yet'} />
            </SelectTrigger>
            <SelectContent>
              {options.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {conn && (
          <div className="sm:col-span-2">
            <ConnectionChip connection={conn} />
          </div>
        )}
        {t.backend === 's3' && t.s3 ? (
          <>
            <FormField id={`${p}-bucket`} label="Bucket">
              <Input id={`${p}-bucket`} value={t.s3.bucket} disabled={disabled} onChange={(e) => onChange({ ...t, s3: { ...t.s3!, bucket: e.target.value } })} placeholder="e.g. bank-opsai-prod-files" className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-region`} label="Region">
              <Input id={`${p}-region`} value={t.s3.region} disabled={disabled} onChange={(e) => onChange({ ...t, s3: { ...t.s3!, region: e.target.value } })} placeholder="e.g. ca-central-1" className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-kms`} label="KMS key alias" hint="The bank’s customer-managed key. Every object is encrypted with it.">
              <Input id={`${p}-kms`} value={t.s3.kmsKeyAlias} disabled={disabled} onChange={(e) => onChange({ ...t, s3: { ...t.s3!, kmsKeyAlias: e.target.value } })} placeholder="e.g. alias/opsai-prod-files" className="font-mono text-sm" />
            </FormField>
            <div className="flex items-start justify-between gap-3 rounded-md border px-3 py-2">
              <div>
                <Label htmlFor={`${p}-lock`}>Object Lock for evidence</Label>
                <p className="text-xs text-muted-foreground">Compliance mode: nobody, including the root account, can delete or shorten retention.</p>
              </div>
              <Switch id={`${p}-lock`} checked={t.s3.objectLockEvidence} disabled={disabled} onCheckedChange={(v) => onChange({ ...t, s3: { ...t.s3!, objectLockEvidence: v } })} />
            </div>
          </>
        ) : t.azure ? (
          <>
            <FormField id={`${p}-account`} label="Storage account">
              <Input id={`${p}-account`} value={t.azure.account} disabled={disabled} onChange={(e) => onChange({ ...t, azure: { ...t.azure!, account: e.target.value } })} placeholder="e.g. bankopsaiprod" className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-container`} label="Container">
              <Input id={`${p}-container`} value={t.azure.container} disabled={disabled} onChange={(e) => onChange({ ...t, azure: { ...t.azure!, container: e.target.value } })} placeholder="e.g. files" className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-scope`} label="Encryption scope" hint="Backed by the bank’s key in Key Vault.">
              <Input id={`${p}-scope`} value={t.azure.encryptionScope} disabled={disabled} onChange={(e) => onChange({ ...t, azure: { ...t.azure!, encryptionScope: e.target.value } })} placeholder="e.g. opsai-prod-cmk" className="font-mono text-sm" />
            </FormField>
            <div className="flex items-start justify-between gap-3 rounded-md border px-3 py-2">
              <div>
                <Label htmlFor={`${p}-immut`}>Immutability policy for evidence</Label>
                <p className="text-xs text-muted-foreground">Locked time-based retention on the evidence container.</p>
              </div>
              <Switch id={`${p}-immut`} checked={t.azure.immutabilityPolicy} disabled={disabled} onCheckedChange={(v) => onChange({ ...t, azure: { ...t.azure!, immutabilityPolicy: v } })} />
            </div>
          </>
        ) : null}
      </div>
      {result && (
        <div className="mt-3">
          <TestResult result={result} />
        </div>
      )}
    </Section>
  );
}

function PurposePicker({ value, onChange, disabled }: { value: FilePurpose[]; onChange: (v: FilePurpose[]) => void; disabled: boolean }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 max-w-64 justify-start truncate font-normal" disabled={disabled}>
          {value.length ? value.map((p) => PURPOSE_LABEL[p]).join(', ') : 'Choose what it applies to'}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-1">
        {PURPOSES.map((p) => (
          <label key={p} className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent">
            <Checkbox checked={value.includes(p)} onCheckedChange={(c) => onChange(c ? [...value, p] : value.filter((x) => x !== p))} />
            {PURPOSE_LABEL[p]}
          </label>
        ))}
      </PopoverContent>
    </Popover>
  );
}

export default function StorageSettingsPage() {
  const { team } = useTeam();
  const admin = team?.scope === 'all';
  const query = useStorageSettings();
  const save = useSaveStorage();
  const test = useTestStorage();
  const s = query.data;
  const saved = React.useMemo(() => (query.data ? toDraft(query.data) : null), [query.data]);
  const [draft, setDraft] = React.useState<StorageSettingsInput | null>(null);
  const [conflict, setConflict] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tests, setTests] = React.useState<Partial<Record<StorageEnvironment, ConnectionTest>>>({});
  const [testing, setTesting] = React.useState<StorageEnvironment | null>(null);
  React.useEffect(() => {
    setDraft(saved);
  }, [saved]);

  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  const set = (patch: Partial<StorageSettingsInput>) => (setDraft((d) => d && { ...d, ...patch }), setError(null));

  const submit = async () => {
    if (!draft) return;
    try {
      const next = await save.mutateAsync(draft);
      setConflict(null);
      setError(null);
      toast.success(`Saved as version ${next.version}`);
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 409) setConflict((e as Error).message);
      else setError((e as Error).message);
    }
  };

  return (
    <SettingsPageLayout section="Storage" description="Where the platform keeps files, what may be uploaded, how files are scanned and how long they are kept.">
      {query.isPending ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : query.isError && !s ? (
        <QueryError what="storage settings" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : s && draft ? (
        <div className="flex flex-col gap-4" data-testid="storage-settings">
          <Alert>
            <Info />
            <AlertDescription>
              Files go from the browser straight to storage on a link that works for one file for a few minutes. The platform keeps the record (name, digest, scan, retention, who uses it), never the bytes.
              {!admin && ' Storage is set by Platform admins; you can see it here.'}
            </AlertDescription>
          </Alert>
          {conflict && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
                {conflict}
                <Button size="sm" variant="outline" onClick={() => (setConflict(null), query.refetch())}>
                  Reload
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <p className="text-xs text-muted-foreground">
            Version {s.version} · saved by {s.updatedBy} {relativeTime(s.updatedAt)}
          </p>

          {draft.targets.map((t, i) => (
            <TargetForm
              key={t.environment}
              t={t}
              disabled={!admin}
              testing={testing === t.environment}
              result={tests[t.environment]}
              onChange={(next) => set({ targets: draft.targets.map((x, j) => (j === i ? next : x)) })}
              onTest={async () => {
                setTesting(t.environment);
                try {
                  const r = await test.mutateAsync(t.environment);
                  setTests((x) => ({ ...x, [t.environment]: r }));
                  if (r.ok) toast.success(`${ENV_LABEL[t.environment]} storage answered`);
                  else toast.warning(`${ENV_LABEL[t.environment]} storage needs attention`, { description: r.steps.find((x) => !x.ok)?.detail });
                } catch (e) {
                  toast.error('Couldn’t test the connection', { description: (e as Error).message });
                } finally {
                  setTesting(null);
                }
              }}
            />
          ))}

          <Section title="Upload limits" description="Checked in the browser before an upload starts and again by the Files API." flush>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>What it is for</TableHead>
                    <TableHead>Allowed types</TableHead>
                    <TableHead className="w-36">Max size</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {draft.limits.map((l, i) => (
                    <TableRow key={l.purpose}>
                      <TableCell className="font-medium whitespace-nowrap">{PURPOSE_LABEL[l.purpose]}</TableCell>
                      <TableCell>
                        <Input
                          aria-label={`Allowed types for ${PURPOSE_LABEL[l.purpose]}`}
                          value={l.allowedTypes.join(', ')}
                          disabled={!admin}
                          onChange={(e) => set({ limits: draft.limits.map((x, j) => (j === i ? { ...x, allowedTypes: e.target.value.split(/[,\s]+/).map((t) => t.replace(/^\./, '').toLowerCase()).filter(Boolean) } : x)) })}
                          className="h-8 min-w-56 font-mono text-xs"
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <Input aria-label={`Max size for ${PURPOSE_LABEL[l.purpose]} in MB`} type="number" min={1} value={l.maxSizeMb} disabled={!admin} onChange={(e) => set({ limits: draft.limits.map((x, j) => (j === i ? { ...x, maxSizeMb: Number(e.target.value) } : x)) })} className="h-8 w-20 tabular-nums" />
                          <span className="text-xs text-muted-foreground">MB</span>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Section>

          <Section title="Scanning" description="A file is not readable by anyone, or any agent, until the scan passes.">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex items-start justify-between gap-3 rounded-md border px-3 py-2">
                <div>
                  <Label htmlFor="scan-on">Scan every upload</Label>
                  <p className="text-xs text-muted-foreground">Infected files are quarantined: not downloadable, and the records that use them show them as blocked.</p>
                </div>
                <Switch id="scan-on" checked={draft.scanning.enabled} disabled={!admin} onCheckedChange={(v) => set({ scanning: { ...draft.scanning, enabled: v } })} />
              </div>
              <FormField id="scan-engine" label="Engine">
                <Select value={draft.scanning.engine} onValueChange={(v) => set({ scanning: { ...draft.scanning, engine: v as StorageSettings['scanning']['engine'] } })} disabled={!admin || !draft.scanning.enabled}>
                  <SelectTrigger id="scan-engine" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="clamav">ClamAV, run by the platform</SelectItem>
                    <SelectItem value="defender">Microsoft Defender for Storage</SelectItem>
                    <SelectItem value="icap">The bank’s ICAP gateway</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
            </div>
          </Section>

          <Section
            title="Retention classes"
            description="Each file gets the class for what it is for. A file under legal hold is kept whatever its class says."
            actions={
              <Button size="sm" variant="outline" disabled={!admin} onClick={() => set({ retentionClasses: [...draft.retentionClasses, { id: `rc_${Date.now().toString(36)}`, name: '', days: 365, purposes: [], worm: false, keepUntilEnd: false }] })}>
                <Plus className="size-3.5" /> Add class
              </Button>
            }
            flush
          >
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead className="w-40">Keep for</TableHead>
                    <TableHead>Applies to</TableHead>
                    <TableHead className="w-24 text-center">Minimum</TableHead>
                    <TableHead className="w-24 text-center">WORM</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {draft.retentionClasses.map((c, i) => {
                    const upd = (p: Partial<typeof c>) => set({ retentionClasses: draft.retentionClasses.map((x, j) => (j === i ? { ...x, ...p } : x)) });
                    return (
                      <TableRow key={c.id}>
                        <TableCell>
                          <Input aria-label="Class name" value={c.name} disabled={!admin} onChange={(e) => upd({ name: e.target.value })} placeholder="e.g. Complaints · 6 years" className="h-8 min-w-48" />
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <Input aria-label={`Days to keep ${c.name}`} type="number" min={1} value={c.days ?? ''} placeholder="Always" disabled={!admin} onChange={(e) => upd({ days: e.target.value ? Number(e.target.value) : null })} className="h-8 w-24 tabular-nums" />
                            <span className="text-xs text-muted-foreground">days</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <PurposePicker value={c.purposes} onChange={(purposes) => upd({ purposes })} disabled={!admin} />
                        </TableCell>
                        <TableCell className="text-center">
                          <Switch aria-label={`Refuse deletes before ${c.name} ends`} checked={c.keepUntilEnd} disabled={!admin} onCheckedChange={(v) => upd({ keepUntilEnd: v })} />
                        </TableCell>
                        <TableCell className="text-center">
                          <span className="inline-flex items-center gap-1">
                            <Switch aria-label={`WORM storage for ${c.name}`} checked={c.worm} disabled={!admin} onCheckedChange={(v) => upd({ worm: v, keepUntilEnd: v || c.keepUntilEnd })} />
                            {c.worm && <Lock className="size-3 text-muted-foreground" />}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="icon" className="size-7" disabled={!admin || c.purposes.includes('evidence_bundle')} onClick={() => set({ retentionClasses: draft.retentionClasses.filter((_, j) => j !== i) })} aria-label={`Remove ${c.name || 'class'}`}>
                            <Trash2 className="size-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            <p className="border-t px-4 py-2 text-xs text-muted-foreground">Minimum: deleting before the period ends is refused. WORM: storage itself refuses changes and deletes until the period ends; evidence bundles always use a WORM class.</p>
          </Section>

          <Section title="Download links">
            <FormField id="signed-minutes" label="Signed link lifetime" hint="Each download is a new link for one file. 1 to 60 minutes.">
              <div className="flex items-center gap-1.5">
                <Input id="signed-minutes" type="number" min={1} max={60} value={draft.signedUrlMinutes} disabled={!admin} onChange={(e) => set({ signedUrlMinutes: Number(e.target.value) })} className="w-24 tabular-nums" />
                <span className="text-sm text-muted-foreground">minutes</span>
              </div>
            </FormField>
          </Section>

          {error && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {dirty && (
            <div data-unsaved-bar className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur">
              <span className="text-sm text-muted-foreground">Unsaved changes</span>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => (setDraft(saved), setError(null))} disabled={save.isPending}>
                  <RotateCcw className="size-3.5" /> Discard
                </Button>
                <LoadingButton size="sm" isLoading={save.isPending} onClick={submit}>
                  Save as version {s.version + 1}
                </LoadingButton>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </SettingsPageLayout>
  );
}
