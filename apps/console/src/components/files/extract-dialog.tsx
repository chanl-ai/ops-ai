'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useDocumentTypes } from '@/hooks/document-type-queries';
import { type ReadResult, useStartExtraction } from '@/hooks/extraction-queries';

/** What each end of the extract workflow means for the person who pressed Extract. */
const READ_OUTCOME: Record<string, string> = {
  saved: 'Its fields are saved on the file.',
  waiting: 'Some fields wait for a person to check them in Human Tasks.',
  needs_manual_read: 'A person said this file needs reading by hand.',
  unreadable: 'No text could be read from it.',
  not_saved: 'The fields were read but not saved on the file.',
};

// Detect classifies the file over the team's types and reads it with the one found (documents-service, c-249/c-335).
const DETECT = '__detect';

/** Reads a file with a document type and version (screen 3 of the documents design). */
export function ExtractDialog({ open, onOpenChange, fileId, fileName, onDone }: { open: boolean; onOpenChange: (open: boolean) => void; fileId: string; fileName: string; onDone: (run: ReadResult) => void }) {
  const types = useDocumentTypes();
  const start = useStartExtraction();
  const router = useRouter();
  const [typeId, setTypeId] = React.useState('');
  const [version, setVersion] = React.useState('latest');
  const [error, setError] = React.useState<string | null>(null);
  // One key per opening: a double click or a retry after a dropped answer reads the same extraction.
  const key = React.useMemo(() => (open ? crypto.randomUUID() : ''), [open]);
  const items = types.data?.items ?? [];
  const chosen = items.find((t) => t.id === typeId);
  const detect = typeId === DETECT;

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setVersion('latest');
    if (!typeId && items.length === 1) setTypeId(items[0].id);
  }, [open, items, typeId]);

  const submit = async () => {
    if (!chosen && !detect) return setError('Choose a document type, or Detect the type.');
    setError(null);
    try {
      const input = chosen ? { documentTypeId: chosen.id, version: version === 'latest' ? undefined : Number(version), typeName: chosen.name } : {};
      const run = await start.mutateAsync({ fileId, input, key });
      if (run.status === 'failed' || run.status === 'cancelled') return setError(`The read stopped (${run.status}). Open run ${run.runId} for the step that failed.`);
      const said = READ_OUTCOME[run.status === 'waiting' ? 'waiting' : (run.outcome ?? '')] ?? `Finished with outcome ${run.outcome ?? 'none'}`;
      // Top centre: the default corner sits over the fields the read just filled.
      toast.success(`Read ${fileName}`, { position: 'top-center', description: said, action: { label: 'Open run', onClick: () => router.push(`/workflows/runs/${encodeURIComponent(run.runId)}`) } });
      onOpenChange(false);
      onDone(run);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Extract"
      description={`${detect ? `Find which of the team's document types ${fileName} is, then read it with that type.` : `Read ${fileName} with a document type.`} The fields it finds show on the file with their confidence and the text they came from.`}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={start.isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={start.isPending} loadingText="Reading…" disabled={!chosen && !detect} data-testid="extract-submit">
            Extract
          </LoadingButton>
        </div>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {error && (
          <Alert variant="destructive" data-testid="extract-error">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <FormField id="extract-type" label="Document type" hint={items.length === 0 && !types.isPending ? 'No document types yet: add one under Document types.' : undefined}>
          <Select value={typeId} onValueChange={(v) => (setTypeId(v), setVersion('latest'))}>
            <SelectTrigger id="extract-type" className="w-full" data-testid="extract-type">
              <SelectValue placeholder={types.isPending ? 'Loading…' : 'Choose a type'} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DETECT} data-testid="extract-detect">
                Detect the type
              </SelectItem>
              {items.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {/* Detect picks the type, and reads with that type's latest version, so there is no version to choose. */}
        {!detect && (
        <FormField id="extract-version" label="Version">
          <Select value={version} onValueChange={setVersion} disabled={!chosen}>
            <SelectTrigger id="extract-version" className="w-full" data-testid="extract-version">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="latest">{chosen ? `Latest (v${chosen.latestVersion})` : 'Latest'}</SelectItem>
              {chosen &&
                Array.from({ length: chosen.latestVersion }, (_, i) => chosen.latestVersion - i).map((v) => (
                  <SelectItem key={v} value={String(v)}>
                    v{v}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </FormField>
        )}
        <p className="text-xs text-muted-foreground" data-testid="extract-estimate">
          Starts the Extract from file workflow as you: {detect ? 'about two model calls (finding the type, then reading it)' : 'about one model call'}, charged to this team. Fields it is unsure of wait for a person in Human Tasks.
        </p>
      </form>
    </DialogShell>
  );
}
