'use client';

import * as React from 'react';
import Link from 'next/link';
import type { UseQueryResult } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { ExternalLink } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';

import { SourceKindIcon } from '@/components/knowledge/knowledge-meta';
import { PageFields } from '@/components/knowledge/page-fields';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FilePicker } from '@/components/shared/file-picker';
import { FileUpload, type UploadItem, uploadsBlocker } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { KeyValues, Section } from '@/components/shared/surface';
import { PRESET_LABEL } from '@/components/sources/ingest-meta';
import { SchedulePicker } from '@/components/sources/schedule-picker';
import { initialValues, SourceValuesForm, valueErrors } from '@/components/sources/source-values-form';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useApproveAiSteps, useCreateSource, usePutSourceItem, useSourceKinds, useSourcePreview } from '@/hooks/knowledge-queries';
import { type AiSwitches, aiDefaults, createInput, firstSyncCalls, PIECES_HIGH, PIECES_LOW } from '@/lib/add-source';
import { appPageHref } from '@/lib/app-links';
import { count, plural } from '@/lib/format';
import type { Schedule, Source, SourceKindOption, SourceKindPreview } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

const STEPS = ['Source', 'What to include', 'Review'] as const;
const PREVIEW_DEBOUNCE_MS = 600;
const PREVIEW_ROWS = 50;

const kindKey = (k: SourceKindOption) => (k.type === 'tool' ? `${k.plugin}/${k.source}` : k.type);
/** What each built-in kind takes in, under its title in step 1. */
const BUILT_IN_HINT: Record<string, string> = { file: 'Upload or pick from Files', text: 'Write or paste', push: 'Sent by your systems through the API' };
const slug = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'page';

/** How a new source's AI steps were approved once it exists: by its creator as owner, refused, or not asked for. */
export type AiApproval = { state: 'approved' } | { state: 'waiting'; reason: string } | { state: 'none' };

/** A value as one line of the Review: lists joined, switches as on or off, nothing as a dash. */
function shown(v: unknown) {
  if (Array.isArray(v)) return v.filter((x) => String(x).trim()).join(', ') || '—';
  if (typeof v === 'boolean') return v ? 'On' : 'Off';
  return v === undefined || v === null || v === '' ? '—' : String(v);
}

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Add source in three steps at one width: the kind (from the kinds the team may add), what to include with a live
 * preview for a kind that offers one, then a review of the schedule, the AI steps with their cost basis and the kind's
 * defaults. Create and sync makes the source attached to `kb` with its first sync running, then asks the AI step
 * approval when a step is on. Closing with changes asks first.
 */
export function AddSourceWizard({
  open,
  onOpenChange,
  kb,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  kb: { id: string; name: string };
  onCreated: (source: Source, approval: AiApproval) => void;
}) {
  const kinds = useSourceKinds(open);
  const create = useCreateSource();
  const putItem = usePutSourceItem();
  const approve = useApproveAiSteps();
  const [step, setStep] = React.useState(1);
  const [key, setKey] = React.useState<string | null>(null);
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [name, setName] = React.useState('');
  const [uploads, setUploads] = React.useState<UploadItem[]>([]);
  const [picked, setPicked] = React.useState<string[]>([]);
  const [page, setPage] = React.useState({ title: '', text: '' });
  const [schedule, setSchedule] = React.useState<Schedule>({ kind: 'manual' });
  const [ai, setAi] = React.useState<AiSwitches>({ questions: false, drafts: false });
  const [attempted, setAttempted] = React.useState(false);
  const [error, setError] = React.useState<string>();
  const [confirmClose, setConfirmClose] = React.useState(false);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setKey(null);
    setValues({});
    setName('');
    setUploads([]);
    setPicked([]);
    setPage({ title: '', text: '' });
    setSchedule({ kind: 'manual' });
    setAi({ questions: false, drafts: false });
    setAttempted(false);
    setError(undefined);
  }, [open]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  const options = kinds.data ?? [];
  const kind = options.find((k) => kindKey(k) === key) ?? null;
  const inputs = kind?.type === 'tool' ? (kind.inputs ?? {}) : {};
  const errors = valueErrors(inputs, values);
  // An empty required field is said once Next was pressed; a malformed value is said as it is typed.
  const shownErrors = Object.fromEntries(Object.entries(errors).filter(([n]) => attempted || !(values[n] === undefined || values[n] === '' || (Array.isArray(values[n]) && !(values[n] as unknown[]).length))));
  const valid = Object.keys(errors).length === 0;
  const fileIds = [...new Set([...uploads.flatMap((u) => (u.phase === 'ready' && u.fileId ? [u.fileId] : [])), ...picked])];
  const nameError = name.trim().length < 2 || name.trim().length > 80 ? 'Name it in 2 to 80 characters.' : undefined;
  const pageErrors = kind?.type === 'text' ? { title: page.title.trim() ? undefined : 'Give the page a title.', text: page.text.trim() ? undefined : 'Write the page’s text.' } : {};
  const filesError = kind?.type === 'file' ? (uploads.length ? uploadsBlocker(uploads) : undefined) ?? (fileIds.length ? undefined : 'Upload or pick at least one file.') : undefined;

  const previewValues = useDebounced(values, PREVIEW_DEBOUNCE_MS);
  const previewing = !!kind?.previews && step >= 2 && valid && Object.keys(valueErrors(inputs, previewValues)).length === 0;
  const preview = useSourcePreview({ plugin: kind?.plugin, source: kind?.source, values: previewValues }, previewing);

  const dirty = !!key;
  const close = (o: boolean) => {
    if (o) return onOpenChange(true);
    if (create.isPending || putItem.isPending || approve.isPending) return;
    if (dirty) return setConfirmClose(true);
    onOpenChange(false);
  };

  const choose = (k: SourceKindOption) => {
    if (kindKey(k) !== key) {
      setKey(kindKey(k));
      setValues(k.type === 'tool' ? initialValues(k.inputs ?? {}) : {});
      setSchedule(k.defaults.schedule);
      setAi(aiDefaults(k));
      setAttempted(false);
    }
    setStep(2);
  };
  const next = () => {
    setAttempted(true);
    if (!valid || nameError || filesError || pageErrors.title || pageErrors.text) return;
    setStep(3);
  };

  const units = kind?.type === 'file' ? fileIds.length : kind?.type === 'text' ? 1 : kind?.type === 'push' ? null : (preview.data?.willFetch ?? null);
  // Typed text and pushed items are indexed when written, so the source has nothing of its own to sync on a schedule.
  const written = kind?.type === 'text' || kind?.type === 'push';
  const calls = units === null ? null : firstSyncCalls(units, ai);

  const submit = async () => {
    if (!kind) return;
    setError(undefined);
    try {
      const s = await create.mutateAsync({ input: createInput({ kind, name, values, schedule, ai, fileIds }), sync: !written, kbIds: [kb.id] });
      if (kind.type === 'text') await putItem.mutateAsync({ id: s.id, input: { name: `${slug(page.title)}.md`, title: page.title.trim(), text: page.text } });
      let approval: AiApproval = { state: 'none' };
      if (ai.questions || ai.drafts) {
        try {
          await approve.mutateAsync(s.id);
          approval = { state: 'approved' };
        } catch (e) {
          approval = { state: 'waiting', reason: (e as Error).message };
        }
      }
      onOpenChange(false);
      onCreated(s, approval);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const groups = [
    { id: 'built_in', label: 'Built in', kinds: options.filter((k) => k.group === 'built_in') },
    { id: 'apps', label: 'From your apps', kinds: options.filter((k) => k.group === 'apps') },
  ].filter((g) => g.kinds.length);

  const footer = (
    <div className="flex w-full items-center justify-end gap-2">
      {error && <p className="mr-auto text-xs text-destructive-text">{error}</p>}
      {step === 1 ? (
        <Button variant="outline" onClick={() => close(false)}>
          Cancel
        </Button>
      ) : (
        <Button variant="outline" onClick={() => setStep(step - 1)} disabled={create.isPending || putItem.isPending || approve.isPending}>
          Back
        </Button>
      )}
      {step === 1 && (
        <Button disabled={!kind} onClick={() => kind && choose(kind)} data-testid="add-source-next">
          Next
        </Button>
      )}
      {step === 2 && (
        <Button onClick={next} data-testid="add-source-next">
          Next
        </Button>
      )}
      {step === 3 && (
        <LoadingButton isLoading={create.isPending || putItem.isPending || approve.isPending} loadingText="Creating…" onClick={submit} data-testid="add-source-create">
          {kind?.type === 'push' ? 'Create' : 'Create and sync'}
        </LoadingButton>
      )}
    </div>
  );

  return (
    <>
      <DialogShell
        open={open}
        onOpenChange={close}
        size="lg"
        title="Add source"
        description={`Its items feed ${kb.name}. Reading, cleaning and splitting start from the kind’s defaults and change later in the source’s Settings.`}
        headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="add-source-stepper" />}
        footer={footer}
        bodyRef={bodyRef}
        panelClassName="sm:h-[min(44rem,90vh)]"
        data-testid="add-source-wizard"
      >
        {step === 1 && (
          <div className="flex flex-col gap-2">
            <Command className="rounded-md border" value={key ?? ''}>
              <CommandInput placeholder="Search kinds of source…" aria-label="Search kinds of source" />
              <CommandList className="max-h-none">
                {kinds.isPending ? (
                  <p className="px-3 py-6 text-center text-sm text-muted-foreground">Loading the kinds your team can add…</p>
                ) : kinds.isError ? (
                  <div className="flex flex-col items-center gap-2 px-3 py-6 text-sm">
                    <p className="text-destructive-text">Couldn’t load the kinds of source: {kinds.error.message}</p>
                    <Button variant="outline" size="sm" onClick={() => kinds.refetch()}>
                      Try again
                    </Button>
                  </div>
                ) : (
                  <>
                    <CommandEmpty>No kind of source matches.</CommandEmpty>
                    {groups.map((g) => (
                      <CommandGroup key={g.id} heading={g.label}>
                        {g.kinds.map((k) => {
                          const notConnected = (!!k.needsConnection && !k.connected) || k.canCreate === false;
                          return (
                            <CommandItem
                              key={kindKey(k)}
                              value={kindKey(k)}
                              keywords={[k.title]}
                              disabled={notConnected}
                              onSelect={() => setKey(kindKey(k))}
                              onDoubleClick={() => !notConnected && choose(k)}
                              className={cn('gap-3 py-2.5', key === kindKey(k) && 'bg-accent')}
                              data-testid={`add-source-kind-${k.type === 'tool' ? k.source : k.type}`}
                            >
                              <SourceKindIcon kind={k.kind} />
                              <span className="min-w-0 flex-1">
                                <span className="block truncate font-medium">{k.title}</span>
                                <span className="block truncate text-xs text-muted-foreground">
                                  {k.type !== 'tool' ? BUILT_IN_HINT[k.type] : k.site ? 'Pages of one website' : k.canCreate === false ? (k.cannotCreateBecause ?? 'Cannot be added') : k.needsConnection ? (k.connected ? 'Connected' : 'Not connected') : 'From the app'}
                                </span>
                              </span>
                              {key === kindKey(k) && <Badge variant="secondary">Chosen</Badge>}
                            </CommandItem>
                          );
                        })}
                      </CommandGroup>
                    ))}
                  </>
                )}
              </CommandList>
            </Command>
            {options
              .filter((k) => k.needsConnection && !k.connected && k.canCreate !== false && k.plugin)
              .map((k) => (
                <p key={kindKey(k)} className="text-xs text-muted-foreground">
                  {k.title} needs a connection first.{' '}
                  <Link href={appPageHref(`plugin:${k.plugin}`)} className="inline-flex items-center gap-1 text-foreground underline underline-offset-4">
                    Connect it on its app page <ExternalLink className="size-3" />
                  </Link>
                </p>
              ))}
            <p className="text-xs text-muted-foreground">Listed from your team’s apps that are on: files are built in, and each app adds the knowledge sources it offers.</p>
          </div>
        )}

        {step === 2 && kind && (
          <div className="flex flex-col gap-5">
            <FormField id="as-name" label="Name" error={attempted ? nameError : undefined}>
              <Input id="as-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={kind.site ? 'e.g. Claims help centre' : 'e.g. Rate sheets'} maxLength={80} aria-invalid={attempted && !!nameError} data-testid="add-source-name" />
            </FormField>
            {kind.type === 'file' ? (
              <div className="flex flex-col gap-4">
                <FormField id="as-files" label="Files" error={attempted ? filesError : undefined} hint="Each upload goes to Files first; picked files are read from there.">
                  <FileUpload id="as-files" purpose="knowledge_source" multiple onChange={setUploads} title="Upload new files" testId="add-source-upload" />
                </FormField>
                <div className="flex flex-col gap-1.5">
                  <p className="text-sm font-medium">Or pick from Files</p>
                  <FilePicker value={picked} onChange={setPicked} testId="add-source-pick" />
                </div>
                {!!fileIds.length && <p className="text-xs text-muted-foreground">{plural(fileIds.length, 'file')} chosen.</p>}
              </div>
            ) : kind.type === 'text' ? (
              <PageFields idPrefix="add-source-page" title={page.title} text={page.text} onTitle={(title) => setPage({ ...page, title })} onText={(text) => setPage({ ...page, text })} titleError={attempted ? pageErrors.title : undefined} textError={attempted ? pageErrors.text : undefined} />
            ) : kind.type === 'push' ? (
              <div className="rounded-md border bg-muted/30 p-3 text-sm" data-testid="add-source-push">
                <p className="font-medium">Items arrive from your systems</p>
                <p className="mt-1 text-muted-foreground">
                  Each item is sent to <code className="font-mono text-xs">POST /v1/sources/&lt;id&gt;/items</code> with a name and its text or file, and is indexed at once. Sending the same name with the same content changes nothing; new content is the item’s next version. The source’s page shows its id once it is created.
                </p>
              </div>
            ) : (
              <>
                <SourceValuesForm idPrefix="as" inputs={inputs} values={values} onChange={setValues} errors={shownErrors} scopeSource={kind.pickers && kind.plugin && kind.source ? { plugin: kind.plugin, source: kind.source } : undefined} />
                {kind.previews && <PreviewPanel paused={!valid} query={preview} />}
              </>
            )}
          </div>
        )}

        {step === 3 && kind && (
          <div className="flex flex-col gap-4">
            <Section title="Source" actions={<EditLink onClick={() => setStep(1)} />}>
              <KeyValues rows={[['Kind', kind.title], ['Name', name.trim()], ['Feeds', kb.name]]} />
            </Section>
            <Section title="What to include" actions={<EditLink onClick={() => setStep(2)} />}>
              <KeyValues
                rows={
                  kind.type === 'file'
                    ? [['Files', plural(fileIds.length, 'file')]]
                    : kind.type === 'text'
                      ? [['Page', page.title.trim()], ['Length', plural(page.text.trim().split(/\s+/).filter(Boolean).length, 'word')]]
                      : kind.type === 'push'
                        ? [['Items', 'Sent through the API']]
                        : [
                        ...Object.keys(inputs).map((n): [string, React.ReactNode] => [n.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()), shown(values[n])]),
                        ...(kind.previews ? [['Pages', preview.data ? `${count(preview.data.willFetch)} of ${count(preview.data.found)} found will be fetched${preview.data.capped ? ' (the listing stopped at its limit)' : ''}` : 'Not previewed'] as [string, React.ReactNode]] : []),
                      ]
                }
              />
            </Section>
            {!written && (
              <Section title="Schedule" description="The first sync starts as soon as you create the source.">
                <SchedulePicker id="as-schedule" value={schedule} onChange={setSchedule} />
              </Section>
            )}
            <Section title="Questions and FAQs" description="Both call a model at each sync, for changed pieces only.">
              <div className="flex flex-col gap-4">
                <AiSwitch id="as-faq" label="Likely questions" hint="A model writes questions each piece answers. They are searched; the piece is returned and cited. No review." checked={ai.questions} onChange={(v) => setAi({ ...ai, questions: v })} />
                <AiSwitch id="as-faq-pairs" label="FAQ drafts" hint="A model drafts question-and-answer pairs. Each waits in Changes for a person to approve, and cites its passage." checked={ai.drafts} onChange={(v) => setAi({ ...ai, drafts: v })} />
                {(ai.questions || ai.drafts) && (
                  <div className="rounded-md border bg-muted/30 p-3 text-sm" data-testid="add-source-cost">
                    <p className="font-medium">Cost basis</p>
                    {calls ? (
                      <p className="mt-1 text-muted-foreground">
                        First sync: about {count(calls.low)} to {count(calls.high)} model calls on {kind.defaults.ingest.model}. That is one call per piece for each step turned on, at {PIECES_LOW} to {PIECES_HIGH} pieces {units === 1 ? 'for the' : 'for each of the'} {plural(units ?? 0, kind.type === 'file' ? 'file' : 'page')}{' '}
                        {kind.type === 'file' ? 'chosen' : 'the preview will fetch'}. A longer {kind.type === 'file' ? 'file' : 'page'} splits into more pieces.
                      </p>
                    ) : (
                      <p className="mt-1 text-muted-foreground">One model call per piece for each step turned on, on {kind.defaults.ingest.model}. How many pieces there are is known after the first sync.</p>
                    )}
                    <p className="mt-1 text-muted-foreground">Later syncs ask only for pieces whose text changed. The price per call is the model alias’s and is not shown here.</p>
                    <p className="mt-1 text-muted-foreground">Creating the source asks the knowledge owner’s approval. Until it is given, syncs run without these steps.</p>
                  </div>
                )}
              </div>
            </Section>
            <Section title="Defaults applied" description="Change them in the source’s Settings once there is content to look at.">
              <KeyValues
                rows={[
                  ['Reading', `OCR ${kind.defaults.parsing.ocr} · tables ${kind.defaults.parsing.tables ? 'on' : 'off'}`],
                  [
                    'Cleaning',
                    [kind.defaults.cleaning.furniture && 'page furniture', kind.defaults.cleaning.mainContent && 'main content only', kind.defaults.cleaning.siteRepeats && 'lines repeated across the site'].filter(Boolean).join(', ') || 'Nothing removed',
                  ],
                  ['Splitting', `${PRESET_LABEL[kind.defaults.ingest.preset] ?? kind.defaults.ingest.preset} · ${count(kind.defaults.ingest.size)}-token pieces, overlap ${count(kind.defaults.ingest.overlap)}`],
                  ['Rules', kind.defaults.rules.length ? plural(kind.defaults.rules.length, 'rule') : 'None'],
                  ['Metadata', kind.defaults.metadataMapping.length ? kind.defaults.metadataMapping.map((m) => m.key).join(', ') : 'None mapped'],
                ]}
              />
            </Section>
          </div>
        )}
      </DialogShell>

      <AlertDialog open={confirmClose} onOpenChange={setConfirmClose}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard this source?</AlertDialogTitle>
            <AlertDialogDescription>Nothing is saved until you create it. Closing now discards what you chose.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction className={buttonVariants({ variant: 'destructive' })} onClick={() => onOpenChange(false)} data-testid="add-source-discard">
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function EditLink({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="link" size="sm" className="h-auto p-0" onClick={onClick}>
      Edit
    </Button>
  );
}

function AiSwitch({ id, label, hint, checked, onChange }: { id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

type PreviewPage = SourceKindPreview['pages'][number];
const PREVIEW_COLUMNS: ColumnDef<PreviewPage>[] = [
  { id: 'page', header: 'Page', cell: ({ row }) => <span className="block max-w-80 truncate font-mono text-xs">{row.original.id}</span> },
  { id: 'outcome', header: 'Outcome', cell: ({ row }) => <span className={cn('text-sm', !row.original.willFetch && 'text-muted-foreground')}>{row.original.outcome}</span> },
];

/** The live preview: each page and its outcome with the counts, or why it is paused, loading or failed. */
function PreviewPanel({ paused, query }: { paused: boolean; query: UseQueryResult<SourceKindPreview> }) {
  if (paused)
    return (
      <div className="rounded-md border border-dashed p-4 text-sm" data-testid="add-source-preview-paused">
        <p className="font-medium">Preview paused</p>
        <p className="text-muted-foreground">The preview runs again when the start address and the rules are valid.</p>
      </div>
    );
  if (query.isPending || (query.isFetching && !query.data)) return <p className="rounded-md border p-4 text-sm text-muted-foreground">Checking what the source would fetch…</p>;
  if (query.isError) return <p className="rounded-md border p-4 text-sm text-destructive-text">The preview could not run: {query.error.message}</p>;
  const p = query.data;
  return (
    <div className="flex flex-col gap-2" data-testid="add-source-preview">
      <p className="text-sm font-medium">
        Live preview · {plural(p.found, 'page')} found, {count(p.willFetch)} will be fetched{p.capped ? ' (the listing stopped at its limit)' : ''}
        {query.isFetching && <span className="ml-2 text-xs font-normal text-muted-foreground">Updating…</span>}
      </p>
      <DataTableWithViews columns={PREVIEW_COLUMNS} data={p.pages.slice(0, PREVIEW_ROWS)} getRowId={(r) => r.id} hideViewSwitcher hidePaginationOnOnePage rowNoun="page" />
      <p className="text-xs text-muted-foreground">robots.txt is always obeyed. Nothing is stored until you create the source.{p.pages.length > PREVIEW_ROWS ? ` The first ${PREVIEW_ROWS} pages are listed.` : ''}</p>
    </div>
  );
}
