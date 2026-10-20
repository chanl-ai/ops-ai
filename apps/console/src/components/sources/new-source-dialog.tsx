'use client';

import * as React from 'react';

import { SOURCE_TYPES, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, type UploadItem, uploadsBlocker } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useAddSourceFiles } from '@/hooks/knowledge-queries';
import type { ConnectionRef } from '@/lib/types/integrations';
import type { Source, SourceInput, SourceType } from '@/lib/types/knowledge';

import { blankSourceInput } from './add-source-dialog';

/** What the Location field asks for, by type: a path for connected apps, a URL list, a start URL, pasted text or files. */
const LOCATION: Partial<Record<SourceType, { label: string; placeholder: string; multiline?: boolean; hint?: string }>> = {
  url: { label: 'URLs, one per line', placeholder: 'e.g. https://intranet.example.com/it/vpn-guide', multiline: true },
  crawl: { label: 'Start URL or sitemap', placeholder: 'e.g. https://www.example.com/help/sitemap.xml', hint: 'Depth 2, at most 200 pages; change both on the source page.' },
  text: { label: 'Text', placeholder: 'e.g. ## Branch hours\nMonday to Friday, 9 to 5.', multiline: true },
};

/**
 * Add a source in one screen: type, name and where to read from. It saves as a draft and opens the source page,
 * where scope, ingestion, rules and schedule are set and the first sync runs. The guided add stays the second button.
 * A file source is created first and then takes its files: each is uploaded to Files, the source adds the ids, and
 * Sync indexes them.
 */
export function NewSourceDialog({
  open,
  onOpenChange,
  connections,
  fixedConnection,
  existingNames,
  isPending,
  onSubmit,
  onSync,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** Connections a connected-app source can read through. */
  connections: ConnectionRef[];
  /** Set when adding from a connection's page: the type and connection are that connection's. */
  fixedConnection?: { id: string; type: SourceType };
  existingNames: string[];
  isPending: boolean;
  /** Creates the source as a draft and returns it. */
  onSubmit: (input: SourceInput) => Promise<Source>;
  /** Starts a sync of the source. */
  onSync: (sourceId: string) => Promise<unknown>;
  /** The source is created, and for a file source its files are uploaded and `synced` says a sync started. */
  onCreated: (source: Source, synced: boolean) => void;
}) {
  const [type, setType] = React.useState<SourceType | ''>('');
  const [name, setName] = React.useState('');
  const [location, setLocation] = React.useState('');
  const [connectionId, setConnectionId] = React.useState('');
  const [files, setFiles] = React.useState<UploadItem[]>([]);
  // A created file source, waiting for its files.
  const [created, setCreated] = React.useState<Source | null>(null);
  const [syncing, setSyncing] = React.useState(false);
  const addFiles = useAddSourceFiles();
  const [errors, setErrors] = React.useState<{ type?: string; name?: string; location?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setType(fixedConnection?.type ?? '');
      setName('');
      setLocation('');
      setConnectionId(fixedConnection?.id ?? '');
      setFiles([]);
      setCreated(null);
      setErrors({});
    }
    // Keyed on the id and type, not the object, which the caller rebuilds on every render.
  }, [open, fixedConnection?.id, fixedConnection?.type]); // eslint-disable-line react-hooks/exhaustive-deps

  const meta = type ? sourceTypeMeta(type) : undefined;
  const usable = connections.filter((c) => (c.status === 'healthy' || c.status === 'expiring') && (!meta?.connected || c.kind === type));
  const loc = type ? LOCATION[type] : undefined;
  const groups = [...new Set(SOURCE_TYPES.map((t) => t.group))];

  const submit = async () => {
    const e = {
      type: type ? undefined : 'Choose what to read from.',
      name: name.trim().length < 2 ? 'Name it in 2 to 80 characters.' : existingNames.some((n) => n.toLowerCase() === name.trim().toLowerCase()) ? 'A source with this name already exists.' : undefined,
      location: !type || type === 'file' ? undefined : meta?.connected && !connectionId ? 'Choose the connection to read through.' : location.trim() ? undefined : `Say where to read from: ${meta?.connected ? meta.scopeLabel.toLowerCase() : (loc?.label.toLowerCase() ?? 'location')}.`,
    };
    setErrors(e);
    if (e.type || e.name || e.location || !type) return;
    try {
      const s = await onSubmit(blankSourceInput({ type, name, connectionId, location, files: [] }));
      if (type === 'file') setCreated(s);
      else onCreated(s, false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };

  // Each finished upload is in Files; the source takes the ids before it syncs or is left for later.
  const finish = async (andSync: boolean) => {
    if (!created) return;
    const blocker = files.length ? uploadsBlocker(files) : andSync ? 'Upload at least one file.' : undefined;
    setErrors({ location: blocker });
    if (blocker) return;
    setSyncing(true);
    try {
      const ids = files.flatMap((f) => (f.fileId ? [f.fileId] : []));
      if (ids.length) await addFiles.mutateAsync({ id: created.id, fileIds: ids });
      if (andSync) await onSync(created.id);
      onCreated(created, andSync);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    } finally {
      setSyncing(false);
    }
  };

  if (created)
    return (
      <DialogShell
        open={open}
        onOpenChange={onOpenChange}
        size="md"
        title={`Add files to ${created.name}`}
        description="Each file goes to Files first, then into the source. Sync reads them and indexes their pages and sections."
        footer={
          <div className="flex w-full items-center justify-end gap-2">
            {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
            <Button variant="outline" onClick={() => finish(false)} disabled={syncing}>
              Sync later
            </Button>
            <LoadingButton isLoading={syncing} loadingText="Starting…" onClick={() => finish(true)} data-testid="new-source-sync">
              Sync
            </LoadingButton>
          </div>
        }
      >
        <FormField id="ns-files" label="Files" error={errors.location}>
          <FileUpload id="ns-files" purpose="knowledge_source" multiple onChange={setFiles} testId="new-source-files" />
        </FormField>
      </DialogShell>
    );

  return (
    <DialogShell
      open={open}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      size="md"
      title="Add source"
      description="Saves a draft. Set scope, ingestion, rules and schedule on the source page, then sync it."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={isPending} data-testid="new-source-submit">
            Add source
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="ns-type" label="Type" error={errors.type}>
          <Select value={type} onValueChange={(v) => (setType(v as SourceType), setLocation(''), setConnectionId(''))} disabled={!!fixedConnection}>
            <SelectTrigger id="ns-type" className="w-full" aria-invalid={!!errors.type} data-testid="new-source-type">
              <SelectValue placeholder="Choose a type" />
            </SelectTrigger>
            <SelectContent>
              {groups.map((g) => (
                <SelectGroup key={g}>
                  <SelectLabel>{g}</SelectLabel>
                  {SOURCE_TYPES.filter((t) => t.group === g).map((t) => (
                    <SelectItem key={t.type} value={t.type}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="ns-name" label="Name" error={errors.name}>
          <Input id="ns-name" aria-invalid={!!errors.name} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Lending policy manuals" maxLength={80} />
        </FormField>
        {meta?.connected && !fixedConnection && (
          <FormField id="ns-conn" label="Connection" error={!connectionId ? errors.location : undefined}>
            <Select value={connectionId} onValueChange={setConnectionId}>
              <SelectTrigger id="ns-conn" className="w-full">
                <SelectValue placeholder={usable.length ? 'Choose a connection' : `No healthy ${meta.label} connection`} />
              </SelectTrigger>
              <SelectContent>
                {usable.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        {type && type !== 'file' && (
          <FormField
            id="ns-location"
            label={meta?.connected ? `${meta.scopeLabel}, one per line` : (loc?.label ?? 'Location')}
            error={meta?.connected && !connectionId ? undefined : errors.location}
            hint={meta?.connected ? 'e.g. a site path, space key or folder. Pick more on the source page.' : loc?.hint}
          >
            {loc?.multiline || meta?.connected ? (
              <Textarea id="ns-location" rows={3} value={location} onChange={(e) => setLocation(e.target.value)} placeholder={loc?.placeholder ?? 'e.g. /sites/policies/Lending'} className="font-mono text-xs" aria-invalid={!!errors.location} />
            ) : (
              <Input id="ns-location" value={location} onChange={(e) => setLocation(e.target.value)} placeholder={loc?.placeholder} aria-invalid={!!errors.location} />
            )}
          </FormField>
        )}
      </div>
    </DialogShell>
  );
}
