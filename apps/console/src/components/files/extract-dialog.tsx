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
import { SearchSelect } from '@/components/shared/search-select';
import { documentTypeOptions, useDocumentType, useDocumentTypes } from '@/hooks/document-type-queries';
import type { OptionSource } from '@/hooks/options-queries';
import { type ReadResult, useStartExtraction } from '@/hooks/extraction-queries';
import { notReadSaid } from '@/lib/not-read-said';
import { cn } from '@/lib/utils';

/** What each end of the extract workflow means for the person who pressed Extract. */
const READ_OUTCOME: Record<string, string> = {
  saved: 'Its fields are saved on the file.',
  waiting: 'Some fields wait for a person to check them in Human Tasks.',
  reading: 'The file is still being read; its fields show here when it finishes.',
  needs_manual_read: 'A person said this file needs reading by hand.',
  unreadable: 'No text could be read from it.',
  not_saved: 'The fields were read but not saved on the file.',
};

// Detect classifies the file over the team's types and reads it with the one found (documents-service).
const DETECT = '__detect';

/** The types the picker offers: Detect first, then the team's types as the person searches (the service searches and pages). */
const typeChoices: OptionSource = {
  key: 'extract-type-options',
  fetch: async (p) => {
    const page = await documentTypeOptions.fetch(p);
    const first = !p.ids && !p.search && !p.cursor;
    return first ? { ...page, data: [{ id: DETECT, label: 'Detect the type', hint: null }, ...page.data] } : page;
  },
};

/** How the file is read: with a document type (or Detect), as its full text, or with fields the model proposes. */
type ReadMode = 'fields' | 'text' | 'propose';
const MODES: { mode: ReadMode; label: string; sub: string; testId: string }[] = [
  { mode: 'fields', label: 'A document type', sub: "Read the fields of one of the team's types, or Detect the type", testId: 'file-read-fields' },
  { mode: 'text', label: 'Full text', sub: "Every page's text with word confidence. No model, no cost", testId: 'file-read-full-text' },
  { mode: 'propose', label: 'Let the model propose the fields', sub: 'Proposes fields from the first 5 pages, then reads them', testId: 'file-read-propose' },
];

/** Reads a file with a document type and version (screen 3 of the documents design). */
export function ExtractDialog({ open, onOpenChange, fileId, fileName, onDone, onFullText }: { open: boolean; onOpenChange: (open: boolean) => void; fileId: string; fileName: string; onDone: (run: ReadResult) => void; /** Full text starts no read: the page shows the file's Text tab, its first `pages` pages when given. */ onFullText?: (pages?: number) => void }) {
  // Two rows say whether the team has none or exactly one; the picker reads the types as the person searches.
  const types = useDocumentTypes({ page: 1, pageSize: 2 });
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
  const only = types.data?.pagination.total === 1 ? types.data.data[0] : undefined;
  const detect = typeId === DETECT;
  // The chosen type's latest version is read by id, so a type beyond any first page is as available as the first.
  const chosenType = useDocumentType(detect ? '' : typeId);
  const chosen = chosenType.data;
  const byType = mode === 'fields';
  const pagesLimit = maxPages.trim() ? Number(maxPages) : undefined;
  const pagesError = pagesLimit !== undefined && (!Number.isInteger(pagesLimit) || pagesLimit < 1) ? 'A whole number of pages, 1 or more.' : undefined;

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setVersion('latest');
    if (!typeId && only) setTypeId(only.id);
  }, [open, only, typeId]);

  const submit = async () => {
    if (!byType && mode === 'text') {
      if (pagesError) return;
      onOpenChange(false);
      return onFullText?.(pagesLimit);
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
      // A read no reply answered waits for a person to type its values: say why before the generic line about fields to check.
      const said = run.notRead ? `${notReadSaid(run.notRead.reason, run.notRead.tries)} Type the required values in Human Tasks.` : READ_OUTCOME[run.status === 'waiting' || run.status === 'reading' ? run.status : (run.outcome ?? '')] ?? `Finished with outcome ${run.outcome ?? 'none'}`;
      // Top centre: the default corner sits over the fields the read just filled.
      toast.success(`Read ${fileName}`, { position: 'top-center', description: said, action: { label: 'Open run', onClick: () => router.push(`/build/runs/${encodeURIComponent(run.runId)}`) } });
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
      
        {mode !== 'fields' && (
          <>
            {mode === 'propose' && (
              <FormField id="extract-hint" label="What is it?" optional hint="Helps the model name the fields.">
                <Input id="extract-hint" value={hint} onChange={(e) => setHint(e.target.value)} placeholder="e.g. a supplier invoice" maxLength={200} data-testid="extract-hint" />
              </FormField>
            )}
            <FormField id="extract-max-pages" label="Pages to read" optional hint="Every page when empty." error={pagesError}>
              <Input id="extract-max-pages" type="number" inputMode="numeric" min={1} value={maxPages} onChange={(e) => setMaxPages(e.target.value)} placeholder="e.g. 10" aria-invalid={!!pagesError} data-testid="extract-max-pages" />
            </FormField>
          </>
        )}
        {byType && (
        <FormField id="extract-type" label="Document type" hint={types.data?.pagination.total === 0 ? 'No document types yet: add one under Document types.' : undefined}>
          <SearchSelect
            source={typeChoices}
            value={typeId ? { id: typeId, label: detect ? 'Detect the type' : (chosen?.name ?? typeId) } : null}
            onChange={(id) => (setTypeId(id), setVersion('latest'))}
            placeholder={types.isPending ? 'Loading…' : 'Choose a type'}
            searchPlaceholder="Search document types…"
            emptyText="No document type matches."
            id="extract-type"
            testId="extract-type"
            className="w-full"
          />
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
