'use client';

import * as React from 'react';
import { AlertCircle, Info, KeyRound, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { BACKEND_LABEL, CREDENTIAL_KIND_LABEL, PURPOSE_LABEL, scanningText } from '@/components/files/file-meta';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { AddMenu } from '@/components/shared/add-menu';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { StepList } from '@/components/shared/step-list';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useRemoveStorageCredential, useSaveStorage, useSetStorageCredential, useStorageCredentials, useStorageSettings, useTestStorage } from '@/hooks/file-queries';
import { STORED_PURPOSES } from '@/lib/file-purposes';
import { relativeTime } from '@/lib/format';
import type { ConnectionTest, FilePurpose, StorageBackendName, StorageCredentialKind, StorageDocument, StorageTarget } from '@/lib/types/files';
import { useCan } from '@/hooks/me-queries';

const PURPOSES = STORED_PURPOSES;
const KIND_FIELDS: Record<StorageCredentialKind, { key: string; label: string; secret?: boolean }[]> = {
  aws_access_key: [
    { key: 'accessKeyId', label: 'Access key ID' },
    { key: 'secretAccessKey', label: 'Secret access key', secret: true },
  ],
  azure_service_principal: [
    { key: 'tenantId', label: 'Directory (tenant) ID' },
    { key: 'clientId', label: 'Application (client) ID' },
    { key: 'clientSecret', label: 'Client secret', secret: true },
  ],
};
const purposeName = (p: StorageTarget['purpose']) => (p === 'default' ? 'Every other purpose' : PURPOSE_LABEL[p]);
const blankTarget = (purpose: StorageTarget['purpose']): StorageTarget => ({ purpose, backend: 'local', container: purpose === 'default' ? 'local' : purpose.replace(/_/g, '-'), region: '', endpoint: '', credential: '', uploadPath: 'proxy', encryption: '' });

function TestResult({ result }: { result: ConnectionTest }) {
  return (
    <div data-testid="storage-test-result">
      <StepList title="Connection test" steps={result.steps.map((st) => ({ title: `${st.label} · ${st.detail}`, state: st.ok ? 'done' : 'failed' }))} />
    </div>
  );
}

function TargetForm({ t, onChange, onRemove, credentials, disabled, error }: { t: StorageTarget; onChange: (t: StorageTarget) => void; onRemove?: () => void; credentials: string[]; disabled: boolean; error?: string }) {
  const test = useTestStorage();
  const [result, setResult] = React.useState<ConnectionTest>();
  const p = `st-${t.purpose}`;
  const cloud = t.backend !== 'local';
  return (
    <Section
      title={purposeName(t.purpose)}
      description={t.purpose === 'default' ? 'Where files go unless their purpose has its own target.' : `Where ${PURPOSE_LABEL[t.purpose].toLowerCase()} files go.`}
      actions={
        <div className="flex gap-2">
          <LoadingButton
            type="button"
            size="sm"
            variant="outline"
            isLoading={test.isPending}
            onClick={async () => {
              try {
                setResult(await test.mutateAsync(t));
              } catch (e) {
                toast.error('Couldn’t test the target', { description: (e as Error).message });
              }
            }}
          >
            Test
          </LoadingButton>
          {onRemove && (
            <Button type="button" size="sm" variant="ghost" onClick={onRemove} disabled={disabled} aria-label={`Remove the ${purposeName(t.purpose)} target`}>
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2" data-testid={`storage-target-${t.purpose}`}>
        <FormField id={`${p}-backend`} label="Backend">
          <Select value={t.backend} onValueChange={(v) => onChange({ ...t, backend: v as StorageBackendName, uploadPath: v === 'local' ? 'proxy' : t.uploadPath, credential: v === 'local' ? '' : t.credential })} disabled={disabled}>
            <SelectTrigger id={`${p}-backend`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(BACKEND_LABEL) as StorageBackendName[]).map((b) => (
                <SelectItem key={b} value={b}>
                  {BACKEND_LABEL[b]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id={`${p}-container`} label={t.backend === 's3' ? 'Bucket' : t.backend === 'azure_blob' ? 'Container' : 'Folder'}>
          <Input id={`${p}-container`} value={t.container} disabled={disabled} onChange={(e) => onChange({ ...t, container: e.target.value })} placeholder="e.g. bank-opsai-files" className="font-mono text-sm" />
        </FormField>
        {cloud && (
          <>
            <FormField id={`${p}-credential`} label="Credential" hint="Signs in to storage. Added under Credentials on this page.">
              <Select value={t.credential} onValueChange={(v) => onChange({ ...t, credential: v })} disabled={disabled}>
                <SelectTrigger id={`${p}-credential`} className="w-full">
                  <SelectValue placeholder={credentials.length ? 'Choose a credential' : 'Add a credential first'} />
                </SelectTrigger>
                <SelectContent>
                  {credentials.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id={`${p}-region`} label="Region" optional>
              <Input id={`${p}-region`} value={t.region} disabled={disabled} onChange={(e) => onChange({ ...t, region: e.target.value })} placeholder="e.g. ca-central-1" className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-endpoint`} label={t.backend === 'azure_blob' ? 'Storage account URL' : 'Endpoint'} optional={t.backend === 's3'} hint={t.backend === 's3' ? 'For S3-compatible storage; empty uses AWS.' : undefined}>
              <Input id={`${p}-endpoint`} value={t.endpoint} disabled={disabled} onChange={(e) => onChange({ ...t, endpoint: e.target.value })} placeholder={t.backend === 's3' ? 'e.g. https://s3.bank.internal' : 'e.g. https://bankopsai.blob.core.windows.net'} className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-encryption`} label={t.backend === 's3' ? 'KMS key alias' : 'Encryption scope'} optional>
              <Input id={`${p}-encryption`} value={t.encryption} disabled={disabled} onChange={(e) => onChange({ ...t, encryption: e.target.value })} placeholder={t.backend === 's3' ? 'e.g. alias/opsai-files' : 'e.g. opsai-cmk'} className="font-mono text-sm" />
            </FormField>
            <FormField id={`${p}-path`} label="Upload path" hint="Through the files service when the bank’s network blocks browsers from storage.">
              <Select value={t.uploadPath} onValueChange={(v) => onChange({ ...t, uploadPath: v as StorageTarget['uploadPath'] })} disabled={disabled}>
                <SelectTrigger id={`${p}-path`} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="direct">Browser to storage</SelectItem>
                  <SelectItem value="proxy">Through the files service</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </>
        )}
      </div>
      {error && (
        <p className="mt-3 text-sm text-destructive" role="alert" data-testid="storage-target-error">
          {error}
        </p>
      )}
      {result && (
        <div className="mt-3">
          <TestResult result={result} />
        </div>
      )}
    </Section>
  );
}

/** Adds or replaces a named credential. Its values go to the files service once and are never shown again. */
function CredentialDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const set = useSetStorageCredential();
  const [name, setName] = React.useState('');
  const [kind, setKind] = React.useState<StorageCredentialKind>('aws_access_key');
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) (setName(''), setKind('aws_access_key'), setValues({}), setError(undefined));
  }, [open]);
  const submit = async () => {
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(name)) return setError('Use capital letters, digits and _, starting with a letter, up to 64.');
    if (KIND_FIELDS[kind].some((f) => !values[f.key]?.trim())) return setError('Fill in every field.');
    try {
      await set.mutateAsync({ name, input: { kind, values: Object.fromEntries(KIND_FIELDS[kind].map((f) => [f.key, values[f.key].trim()])) } });
      // Cleared at once, so the secret leaves the page with the dialog.
      setValues({});
      toast.success(`Saved credential ${name}`, { description: 'Its values are kept encrypted and never shown again.' });
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title="Add a storage credential"
      description="Kept encrypted by the files service. After saving, only its name and when it was set are shown."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={set.isPending} loadingText="Saving…" data-testid="credential-save">
            Save credential
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="cred-name" label="Name" error={error} hint="Capital letters, digits and _, like tool secrets. Targets refer to it by this name; saving the same name again replaces it.">
          <Input id="cred-name" value={name} onChange={(e) => (setName(e.target.value), setError(undefined))} placeholder="e.g. BANK_S3" className="font-mono text-sm" />
        </FormField>
        <FormField id="cred-kind" label="Kind">
          <Select value={kind} onValueChange={(v) => (setKind(v as StorageCredentialKind), setValues({}))}>
            <SelectTrigger id="cred-kind" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(CREDENTIAL_KIND_LABEL) as StorageCredentialKind[]).map((k) => (
                <SelectItem key={k} value={k}>
                  {CREDENTIAL_KIND_LABEL[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {KIND_FIELDS[kind].map((f) => (
          <FormField key={f.key} id={`cred-${f.key}`} label={f.label}>
            <Input id={`cred-${f.key}`} type={f.secret ? 'password' : 'text'} autoComplete="off" value={values[f.key] ?? ''} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} className="font-mono text-sm" />
          </FormField>
        ))}
      </div>
    </DialogShell>
  );
}

/**
 * Where each upload purpose stores its bytes, the credentials storage is signed in with, upload limits, retention per
 * purpose and download link lifetime (files-service `/v1/settings/storage`, c-100). An admin on the Security team
 * changes it; a save is a new version, made with the Save button only, and each new or changed target is tested
 * before the version is written.
 */
export default function StorageSettingsPage() {
  const admin = useCan('settings', 'manage') === true;
  const query = useStorageSettings();
  const creds = useStorageCredentials();
  const removeCred = useRemoveStorageCredential();
  const save = useSaveStorage();
  const s = query.data;
  const saved = React.useMemo(() => (s ? s.document : null), [s]);
  const [draft, setDraft] = React.useState<StorageDocument | null>(null);
  const [conflict, setConflict] = React.useState<string | null>(null);
  const [error, setError] = React.useState<{ message: string; purpose?: string } | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [removing, setRemoving] = React.useState<string | null>(null);
  React.useEffect(() => {
    setDraft(saved && structuredClone(saved));
  }, [saved]);

  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  const set = (patch: Partial<StorageDocument>) => (setDraft((d) => d && { ...d, ...patch }), setError(null));
  const credentialNames = (creds.data ?? []).map((c) => c.name);
  const targets = draft?.targets.length ? draft.targets : [];
  const unused = PURPOSES.filter((p) => !targets.some((t) => t.purpose === p));

  const submit = async () => {
    if (!draft || !s) return;
    try {
      const next = await save.mutateAsync({ version: s.version, document: draft });
      setConflict(null);
      setError(null);
      toast.success(`Saved as version ${next.version}`);
    } catch (e) {
      const err = e as Error & { status?: number; details?: { purpose?: string } };
      if (err.status === 409 && /version/.test(err.message)) setConflict(err.message);
      else setError({ message: err.message, purpose: err.details?.purpose });
    }
  };

  return (
    <SettingsPageLayout section="Storage" description="Where each kind of file is stored, with which credentials, what may be uploaded and how long files are kept.">
      {query.isPending ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : query.isError && !s ? (
        <QueryError what="storage settings" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : s && draft ? (
        <div className="flex flex-col gap-4" data-testid="storage-settings">
          <Alert>
            <Info />
            <AlertDescription>
              A change of target applies to new uploads; files already stored stay where they are and stay readable. {scanningText(s.scanning)}
              {!admin && ' Only an admin on the Security team changes storage; you can see it here.'}
            </AlertDescription>
          </Alert>
          {conflict && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
                {conflict}
                <Button type="button" size="sm" variant="outline" onClick={() => (setConflict(null), query.refetch())}>
                  Reload
                </Button>
              </AlertDescription>
            </Alert>
          )}
          <p className="text-xs text-muted-foreground" data-testid="storage-version">
            {s.version ? `Version ${s.version} · saved by ${s.updatedBy} ${relativeTime(s.updatedAt ?? '')}` : 'Not saved yet: every file goes to the files service’s own disk.'}
          </p>

          <Section
            title="Credentials"
            description="Keys the files service signs in to storage with. Their values are never shown after saving."
            actions={
              <Button type="button" size="sm" variant="outline" disabled={!admin} onClick={() => setAdding(true)} data-testid="credential-add">
                <KeyRound className="size-3.5" /> Add credential
              </Button>
            }
            flush
          >
            {creds.isPending ? (
              <div className="flex flex-col gap-2 p-4" data-testid="storage-credentials-loading">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : creds.isError && !creds.data ? (
              <QueryError what="storage credentials" onRetry={() => creds.refetch()} retrying={creds.isFetching} error={creds.error} testId="storage-credentials-error" />
            ) : credentialNames.length ? (
              <Table data-testid="storage-credentials">
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Set</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(creds.data ?? []).map((c) => (
                    <TableRow key={c.name}>
                      <TableCell className="font-mono text-sm">{c.name}</TableCell>
                      <TableCell>{CREDENTIAL_KIND_LABEL[c.kind]}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {relativeTime(c.setAt)} by {c.setBy}
                      </TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          disabled={!admin}
                          aria-label={`Remove ${c.name}`}
                          onClick={() => setRemoving(c.name)}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="px-4 py-3 text-sm text-muted-foreground">No credentials yet. Add one before pointing a purpose at S3 or Azure Blob.</p>
            )}
          </Section>

          {targets.length === 0 ? (
            <Section title="Where files go" description="Every purpose uses the files service’s own disk until you set a default target.">
              <Button type="button" size="sm" variant="outline" disabled={!admin} onClick={() => set({ targets: [blankTarget('default')] })} data-testid="target-default-add">
                <Plus className="size-3.5" /> Set a default target
              </Button>
            </Section>
          ) : (
            targets.map((t, i) => (
              <TargetForm
                key={t.purpose}
                t={t}
                credentials={credentialNames}
                disabled={!admin}
                error={error?.purpose === t.purpose ? error.message : undefined}
                onChange={(next) => set({ targets: targets.map((x, j) => (j === i ? next : x)) })}
                onRemove={t.purpose === 'default' ? undefined : () => set({ targets: targets.filter((_, j) => j !== i) })}
              />
            ))
          )}
          {targets.length > 0 && unused.length > 0 && (
            <div>
              <AddMenu label="Add a target for a purpose" items={unused.map((p) => ({ value: p, label: PURPOSE_LABEL[p] }))} onSelect={(p) => set({ targets: [...targets, blankTarget(p as FilePurpose)] })} disabled={!admin} testId="target-add" />
            </div>
          )}

          <Section title="Upload limits" description="Checked by the files service on every upload. Empty means the service-wide limit." flush>
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
                  {PURPOSES.map((p) => {
                    const l = draft.limits.find((x) => x.purpose === p);
                    const put = (patch: { allowedTypes?: string[]; maxSizeMb?: number }) => {
                      const next = { purpose: p, allowedTypes: l?.allowedTypes ?? [], maxSizeMb: l?.maxSizeMb ?? 100, ...patch };
                      set({ limits: [...draft.limits.filter((x) => x.purpose !== p), next] });
                    };
                    return (
                      <TableRow key={p}>
                        <TableCell className="font-medium whitespace-nowrap">{PURPOSE_LABEL[p]}</TableCell>
                        <TableCell>
                          <Input aria-label={`Allowed types for ${PURPOSE_LABEL[p]}`} value={(l?.allowedTypes ?? []).join(', ')} disabled={!admin} placeholder="Any" onChange={(e) => put({ allowedTypes: e.target.value.split(/[,\s]+/).map((t) => t.replace(/^\./, '').toLowerCase()).filter(Boolean) })} className="h-8 min-w-56 font-mono text-xs" />
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <Input aria-label={`Max size for ${PURPOSE_LABEL[p]} in MB`} type="number" min={1} value={l?.maxSizeMb ?? ''} placeholder="100" disabled={!admin} onChange={(e) => put({ maxSizeMb: Number(e.target.value) })} className="h-8 w-20 tabular-nums" />
                            <span className="text-xs text-muted-foreground">MB</span>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </Section>

          <Section title="Retention" description="The class a new file of each purpose is kept under. Classes are defined by the deployment." flush>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>What it is for</TableHead>
                    <TableHead>Kept under</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {PURPOSES.map((p) => (
                    <TableRow key={p}>
                      <TableCell className="font-medium whitespace-nowrap">{PURPOSE_LABEL[p]}</TableCell>
                      <TableCell>
                        <Select
                          value={draft.retention.find((r) => r.purpose === p)?.retentionClass ?? '__default'}
                          onValueChange={(v) => set({ retention: [...draft.retention.filter((r) => r.purpose !== p), ...(v === '__default' ? [] : [{ purpose: p, retentionClass: v }])] })}
                          disabled={!admin}
                        >
                          <SelectTrigger className="h-8 w-64" aria-label={`Retention for ${PURPOSE_LABEL[p]}`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__default">The deployment’s default</SelectItem>
                            {s.retentionClasses.map((c) => (
                              <SelectItem key={c.id} value={c.id}>
                                {c.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Section>

          <Section title="Download links">
            <FormField id="link-minutes" label="Signed link lifetime" hint="Each download is a new link for one file. 1 to 60 minutes.">
              <div className="flex items-center gap-1.5">
                <Input id="link-minutes" type="number" min={1} max={60} value={Math.round(draft.downloadLinkSeconds / 60)} disabled={!admin} onChange={(e) => set({ downloadLinkSeconds: Math.max(1, Number(e.target.value)) * 60 })} className="w-24 tabular-nums" />
                <span className="text-sm text-muted-foreground">minutes</span>
              </div>
            </FormField>
          </Section>

          {error && !error.purpose && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          )}

          {dirty && (
            <div data-unsaved-bar className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur">
              <span className="text-sm text-muted-foreground">Unsaved changes</span>
              <div className="flex gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => (setDraft(saved && structuredClone(saved)), setError(null))} disabled={save.isPending}>
                  <RotateCcw className="size-3.5" /> Discard
                </Button>
                <LoadingButton type="button" size="sm" isLoading={save.isPending} onClick={submit} data-testid="storage-save">
                  Save as version {s.version + 1}
                </LoadingButton>
              </div>
            </div>
          )}
        </div>
      ) : null}
      <CredentialDialog open={adding} onOpenChange={setAdding} />
      <DeleteDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        entityType="credential"
        entityName={removing ?? undefined}
        verb="Remove"
        description="Targets that sign in with it fail their test until they name another credential. The values cannot be recovered."
        isLoading={removeCred.isPending}
        onConfirm={async () => {
          const name = removing!;
          try {
            await removeCred.mutateAsync(name);
            toast.success(`Removed ${name}`);
            setRemoving(null);
          } catch (e) {
            toast.error(`Couldn’t remove ${name}`, { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
