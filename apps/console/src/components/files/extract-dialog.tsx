'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useDocumentTypes } from '@/hooks/document-type-queries';
import { type ReadResult, useStartExtraction } from '@/hooks/extraction-queries';
import { useDocumentReads } from '@/hooks/use-switches';
import { cn } from '@/lib/utils';

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

/** How the file is read: with a document type (or Detect), as its full text, or with fields the model proposes. */
type ReadMode = 'fields' | 'text' | 'propose';
const MODES: { mode: ReadMode; label: string; sub: string; testId: string }[] = [
  { mode: 'fields', label: 'A document type', sub: "Read the fields of one of the team's types, or Detect the type", testId: 'file-read-fields' },
  { mode: 'text', label: 'Full text', sub: "Every page's text with word confidence. No model, no cost", testId: 'file-read-full-text' },
  { mode: 'propose', label: 'Let the model propose the fields', sub: 'Proposes fields from the first 5 pages, then reads them', testId: 'file-read-propose' },
];

/** Reads a file with a document type and version (screen 3 of the documents design). */
export function ExtractDialog({ open, onOpenChange, fileId, fileName, onDone, onFullText }: { open: boolean; onOpenChange: (open: boolean) => void; fileId: string; fileName: string; onDone: (run: ReadResult) => void; /** Full text starts no read: the page shows the file's Text tab. */ onFullText?: () => void }) {
  const reads = useDocumentReads();
  const types = useDocumentTypes();
  const start = useStartExtraction();
  const router = useRouter();
  const [typeId, setTypeId] = React.useState('');
  const [version, setVersion] = React.useState('latest');
  const [error, setError] = React.useState<string | null>(null);
  const [mode, setMode] = React.useState<ReadMode>('fields');
  const [hint, setHint] = React.useState('');
  const [maxPages, setMaxPages] = React.useState('');
  // One key per opening: a double click or a retry after a dropped answer reads the same extraction.
  const key = React.useMemo(() => (open ? crypto.randomUUID() : ''), [open]);
  const items = types.data?.items ?? [];
  const chosen = items.find((t) => t.id === typeId);
  const detect = typeId === DETECT;
  const byType = !reads || mode === 'fields';
  const pagesLimit = maxPages.trim() ? Number(maxPages) : undefined;
  const pagesError = pagesLimit !== undefined && (!Number.isInteger(pagesLimit) || pagesLimit < 1) ? 'A whole number of pages, 1 or more.' : undefined;

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setVersion('latest');
    if (!typeId && items.length === 1) setTypeId(items[0].id);
  }, [open, items, typeId]);

  const submit = async () => {
    if (!byType && mode === 'text') {
      onOpenChange(false);
      return onFullText?.();
    }
    if (byType && !chosen && !detect) return setError('Choose a document type, or Detect the type.');
    if (!byType && pagesError) return;
    setError(null);
    try {
      const input = !byType
        ? { read: 'propose' as const, ...(hint.trim() ? { hint: hint.trim() } : {}), ...(pagesLimit ? { maxPages: pagesLimit } : {}) }
        : chosen
          ? { documentTypeId: chosen.id, version: version === 'latest' ? undefined : Number(version), typeName: chosen.name }
          : {};
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
      description={
        !byType && mode === 'text'
          ? `Show every page of ${fileName} as text, with words read with low confidence marked.`
          : !byType
            ? `Let the model propose the fields ${fileName} holds, then read it with them. Save the fields as a document type to read files like it again.`
            : `${detect ? `Find which of the team's document types ${fileName} is, then read it with that type.` : `Read ${fileName} with a document type.`} The fields it finds show on the file with their confidence and the text they came from.`
      }
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={start.isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={start.isPending} loadingText="Reading…" disabled={byType ? !chosen && !detect : !!pagesError} data-testid="extract-submit">
            {!byType && mode === 'text' ? 'Show text' : 'Extract'}
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
        {reads && (
          <FormField id="extract-mode" label="What to read">
            <RadioGroup id="extract-mode" value={mode} onValueChange={(v) => (setMode(v as ReadMode), setError(null))} className="flex flex-col gap-2">
              {MODES.map((m) => (
                <label key={m.mode} htmlFor={`extract-mode-${m.mode}`} className={cn('flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5', mode === m.mode && 'border-primary bg-primary/5')} data-testid={m.testId}>
                  <RadioGroupItem value={m.mode} id={`extract-mode-${m.mode}`} className="mt-0.5" />
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-sm font-medium">{m.label}</span>
                    <span className="text-xs text-muted-foreground">{m.sub}</span>
                  </span>
                </label>
              ))}
            </RadioGroup>
          </FormField>
        )}
        {reads && mode === 'propose' && (
          <>
            <FormField id="extract-hint" label="What is it?" optional hint="Helps the model name the fields.">
              <Input id="extract-hint" value={hint} onChange={(e) => setHint(e.target.value)} placeholder="e.g. a supplier invoice" maxLength={200} data-testid="extract-hint" />
            </FormField>
            <FormField id="extract-max-pages" label="Pages to read" optional hint="Every page when empty." error={pagesError}>
              <Input id="extract-max-pages" type="number" inputMode="numeric" min={1} value={maxPages} onChange={(e) => setMaxPages(e.target.value)} placeholder="e.g. 10" aria-invalid={!!pagesError} data-testid="extract-max-pages" />
            </FormField>
          </>
        )}
        {byType && (
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
        )}
        {/* Detect picks the type, and reads with that type's latest version, so there is no version to choose. */}
        {byType && !detect && (
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
          {!byType && mode === 'text'
            ? 'No model call and no cost: the text layer is read, and scanned pages through OCR.'
            : `Starts the Extract from file workflow as you: ${!byType ? 'about two model calls (proposing the fields from the first 5 pages, then reading them)' : detect ? 'about two model calls (finding the type, then reading it)' : 'about one model call'}, charged to this team. Fields it is unsure of wait for a person in Human Tasks.`}
        </p>
      </form>
    </DialogShell>
  );
}
