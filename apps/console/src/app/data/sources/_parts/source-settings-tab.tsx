'use client';

import * as React from 'react';
import Link from 'next/link';
import { Layers, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { RULE_FIELDS, RULE_PLACEHOLDER } from '@/components/knowledge/knowledge-meta';
import { PageSaveActions } from '@/components/shared/page-save-actions';
import { MetadataMappingEditor } from '@/components/sources/metadata-mapping-editor';
import { PRESET_LABEL } from '@/components/sources/ingest-meta';
import { SchedulePicker } from '@/components/sources/schedule-picker';
import { SourceValuesForm, valueErrors } from '@/components/sources/source-values-form';
import { DangerZone } from '@/components/shared/danger-zone';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useAiEstimate, useDecideAiSteps, useSourceKinds, useUpdateSource } from '@/hooks/knowledge-queries';
import { count, dateTime, plural, relativeTime } from '@/lib/format';
import type { CleaningSettings, OcrMode, Rule, Sensitivity, SourceDetail, SourcePatch, SyncRun } from '@/lib/types/knowledge';
import type { IngestSettings, IngestStrategy } from '@/lib/types/knowledge-ingest';

type Draft = Required<Pick<SourcePatch, 'name' | 'collection' | 'sensitivity' | 'tags' | 'parsing' | 'cleaning' | 'ingest' | 'rules' | 'metadataMapping' | 'schedule'>> & { values: Record<string, unknown> };

const valuesOf = (src: SourceDetail) => ((src.config.values ?? {}) as Record<string, unknown>);
const pick = (src: SourceDetail): Draft => ({
  name: src.name,
  collection: src.collection,
  sensitivity: src.sensitivity,
  tags: src.tags,
  parsing: src.parsing,
  cleaning: src.cleaning,
  ingest: src.ingest,
  rules: src.rules,
  metadataMapping: src.metadataMapping,
  schedule: src.schedule,
  values: valuesOf(src),
});
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
/** The website inputs a source's Settings edits; the rest are set when it is added. */
const RULE_INPUTS = ['include', 'exclude', 'depth', 'rate'];
const MIN_SIZE = 100;
const MAX_SIZE = 2000;

const OCR: Record<OcrMode, string> = { off: 'Off', auto: 'Auto', always: 'Always' };
const SPLITTERS: { value: IngestStrategy; label: string; hint: string }[] = [
  { value: 'structure', label: 'At headings', hint: 'Sections split at headings; a long one splits at sentences.' },
  { value: 'fixed', label: 'Fixed size', hint: 'Equal windows of tokens with overlap, ignoring headings.' },
];

/** What the backend refuses in a split, said before the save is sent. */
function splitError(i: IngestSettings) {
  if (!Number.isInteger(i.size) || i.size < MIN_SIZE || i.size > MAX_SIZE) return { size: `Piece size is ${MIN_SIZE} to ${count(MAX_SIZE)} tokens.` };
  if (!Number.isInteger(i.overlap) || i.overlap < 0 || i.overlap >= i.size) return { overlap: 'Overlap is zero or more and smaller than the piece size.' };
  if (i.strategies.includes('parent_child') && !(i.childSize > 0 && i.childSize < i.size)) return { childSize: 'Child pieces are smaller than the piece size.' };
  return {};
}

function SwitchRow({ id, label, hint, checked, onChange, children }: { id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; children?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <p className="text-xs text-muted-foreground">{hint}</p>
        {children}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

/**
 * A source's settings as kb-service stores and applies them: reading, cleaning, splitting, likely questions and FAQ
 * drafts with their cost estimate and approval, rules, metadata and schedule. Saving sends only what changed; a change
 * to how items are read, cleaned or split rebuilds them in the background, shown with a link to Sync history.
 */
export function SourceSettingsTab({ source, onDelete }: { source: SourceDetail; onDelete: () => void }) {
  const update = useUpdateSource(source.id);
  const decide = useDecideAiSteps(source.id);
  const kinds = useSourceKinds(source.type === 'tool');
  const saved = React.useMemo(() => pick(source), [source]);
  // Only what the person changed is held; everything else reads from the saved source, so an approval or a save made
  // elsewhere shows at once and is never sent back stale.
  const [edits, setEdits] = React.useState<Partial<Draft>>({});
  const d: Draft = React.useMemo(() => ({ ...saved, ...edits, ingest: { ...(edits.ingest ?? saved.ingest), approval: saved.ingest.approval } }), [saved, edits]);
  const [rebuild, setRebuild] = React.useState<SyncRun | null>(null);
  React.useEffect(() => {
    setEdits({});
  }, [source.id]);

  const cfg = source.config as { plugin?: string; source?: string };
  const kind = kinds.data?.find((k) => k.plugin === cfg.plugin && k.source === cfg.source);
  const ruleInputs = Object.fromEntries(Object.entries(kind?.inputs ?? {}).filter(([n]) => RULE_INPUTS.includes(n)));
  const web = source.kind === 'web';
  const savedAi = saved.ingest.strategies.some((x) => x === 'faq' || x === 'faq_pairs');
  const estimate = useAiEstimate(source.id, savedAi);
  const approval = source.ingest.approval;

  const changed = (Object.keys(edits) as (keyof Draft)[]).filter((k) => !same(d[k], saved[k]));
  const dirty = changed.length > 0;
  const nameError = d.name.trim().length < 2 || d.name.trim().length > 80 ? 'Name it in 2 to 80 characters.' : undefined;
  const sizeErrors: Record<string, string | undefined> = splitError(d.ingest);
  const valuesErrors = Object.keys(ruleInputs).length ? valueErrors(ruleInputs, d.values) : {};
  const invalid = !!nameError || Object.values(sizeErrors).some(Boolean) || Object.keys(valuesErrors).length > 0;

  React.useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setEdits((x) => ({ ...x, [k]: v }));
  const setIngest = (p: Partial<IngestSettings>) => set('ingest', { ...d.ingest, ...p });
  const setCleaning = (p: Partial<CleaningSettings>) => set('cleaning', { ...d.cleaning, ...p });
  const has = (s: IngestStrategy) => d.ingest.strategies.includes(s);
  const toggle = (s: IngestStrategy, on: boolean) => setIngest({ strategies: on ? [...d.ingest.strategies.filter((x) => x !== s), s] : d.ingest.strategies.filter((x) => x !== s) });
  const splitter = SPLITTERS.find((x) => has(x.value))?.value;
  const setSplitter = (s: IngestStrategy) =>
    setIngest({ strategies: [s, ...d.ingest.strategies.filter((x) => !SPLITTERS.some((p) => p.value === x) && !(s === 'fixed' && x === 'parent_child'))] });
  const setRule = (i: number, p: Partial<Rule>) => set('rules', d.rules.map((r, j) => (j === i ? { ...r, ...p } : r)));

  const save = async () => {
    if (invalid) return;
    // Only what changed is sent; the service merges each part key by key and validates the whole.
    const patch = Object.fromEntries(changed.map((k) => [k, d[k]])) as SourcePatch;
    if (patch.values) patch.values = Object.fromEntries(Object.entries(d.values).filter(([k, v]) => !same(v, saved.values[k])));
    // The approval is the knowledge owner's, on its own route; a save never sends it.
    if (patch.ingest) patch.ingest = { ...d.ingest, approval: undefined } as unknown as IngestSettings;
    try {
      const out = await update.mutateAsync(patch);
      setRebuild(out.rebuild ?? null);
      setEdits({});
      toast.success('Settings saved', { description: out.rebuild ? 'Items are being rebuilt in the background.' : undefined });
    } catch (e) {
      toast.error('Couldn’t save settings', { description: (e as Error).message });
    }
  };
  const discard = () => {
    const before = edits;
    setEdits({});
    toast('Changes discarded', { action: { label: 'Undo', onClick: () => setEdits(before) } });
  };
  const decideSteps = (decision: 'approve' | 'revoke') =>
    decide.mutate(decision, {
      onSuccess: () => toast.success(decision === 'approve' ? 'AI steps approved' : 'Approval taken back', { description: decision === 'approve' ? 'The pieces are rebuilt with them in the background.' : 'Syncs run without them until they are approved again.' }),
      onError: (e) => toast.error('Couldn’t record the decision', { description: e.message }),
    });
  const shownRebuild = rebuild ?? (source.rebuild?.status === 'running' ? source.rebuild : null);

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      {shownRebuild && (
        <Alert data-testid="rebuild-notice">
          <Layers className="size-4" />
          <AlertTitle>Saving rebuilds {plural(shownRebuild.counts.total ?? source.itemCount, 'item')} in the background</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <p>Pieces are cut again from the stored readings, and questions are written for changed pieces only. Nothing is fetched again. You can cancel it from Sync history.</p>
            <Button size="sm" variant="outline" asChild>
              <Link href={`/data/sources/${source.id}?tab=history&run=${shownRebuild.id}`}>Open Sync history</Link>
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <SettingsSection title="Source" description="Its name and where it belongs">
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="set-name" label="Name" error={nameError}>
            <Input id="set-name" className="bg-background" value={d.name} onChange={(e) => set('name', e.target.value)} aria-invalid={!!nameError} />
          </FormField>
          <FormField id="set-collection" label="Collection" hint="The department boundary a knowledge base can be limited to.">
            <Input id="set-collection" className="bg-background" value={d.collection} onChange={(e) => set('collection', e.target.value)} placeholder="e.g. Lending" />
          </FormField>
          <FormField id="set-sens" label="Sensitivity">
            <Select value={d.sensitivity} onValueChange={(v) => set('sensitivity', v as Sensitivity)}>
              <SelectTrigger id="set-sens" className="w-full bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="internal">Internal</SelectItem>
                <SelectItem value="confidential">Confidential</SelectItem>
                <SelectItem value="restricted">Restricted</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="set-tags" label="Tags on every item" optional>
            <TagInput id="set-tags" value={d.tags} onChange={(v) => set('tags', v)} placeholder="e.g. policy" />
          </FormField>
        </div>
        <FieldRow label="Takes in" value={source.scopeSummary} />
      </SettingsSection>

      <SettingsSection title="Reading" description="How each file or page is read before it is cleaned">
        <FormField id="set-ocr" label="OCR" hint="Auto reads scanned pages and the picture parts of mixed pages. Changing it reads every file again.">
          <Select value={d.parsing.ocr} onValueChange={(v) => set('parsing', { ...d.parsing, ocr: v as OcrMode })}>
            <SelectTrigger id="set-ocr" className="w-40 bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(OCR) as OcrMode[]).map((o) => (
                <SelectItem key={o} value={o}>
                  {OCR[o]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </SettingsSection>

      <SettingsSection title="Cleaning" description="What is removed between reading and splitting">
        <div className="flex flex-col gap-4">
          <SwitchRow id="set-furniture" label="Remove page furniture" hint="Menus, footers, cookie banners and other blocks the reading marked." checked={d.cleaning.furniture} onChange={(v) => setCleaning({ furniture: v })} />
          <SwitchRow id="set-main" label="Main content only" hint="Keeps the page’s main article when it has one." checked={d.cleaning.mainContent} onChange={(v) => setCleaning({ mainContent: v })} />
          {web && <SwitchRow id="set-repeats" label="Lines repeated across the site" hint="Drops a line found on more than half of this source’s pages." checked={d.cleaning.siteRepeats} onChange={(v) => setCleaning({ siteRepeats: v })} />}
          <FormField id="set-dupes" label="Duplicates" hint="An item with the same cleaned text as another in a knowledge base this source feeds.">
            <Select value={d.cleaning.duplicates} onValueChange={(v) => setCleaning({ duplicates: v as CleaningSettings['duplicates'] })}>
              <SelectTrigger id="set-dupes" className="w-64 bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="flag">Flag both, search the newer</SelectItem>
                <SelectItem value="skip">Skip the new copy</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
        </div>
      </SettingsSection>

      <SettingsSection title="Splitting" description={`How items become pieces. Preset: ${PRESET_LABEL[saved.ingest.preset] ?? saved.ingest.preset}.`}>
        <div className="flex flex-col gap-4">
          <FormField id="set-split" label="Split" hint={SPLITTERS.find((x) => x.value === splitter)?.hint ?? (has('table_rows') ? 'One piece per table row.' : undefined)}>
            {has('table_rows') ? (
              <p id="set-split" className="text-sm">
                Table rows
              </p>
            ) : (
              <Select value={splitter} onValueChange={(v) => setSplitter(v as IngestStrategy)}>
                <SelectTrigger id="set-split" className="w-48 bg-background">
                  <SelectValue placeholder="Choose" />
                </SelectTrigger>
                <SelectContent>
                  {SPLITTERS.map((x) => (
                    <SelectItem key={x.value} value={x.value}>
                      {x.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="set-size" label="Piece size (tokens)" hint={`${MIN_SIZE} to ${count(MAX_SIZE)}.`} error={sizeErrors.size}>
              <Input id="set-size" type="number" className="w-32 bg-background tabular-nums" value={d.ingest.size} aria-invalid={!!sizeErrors.size} onChange={(e) => setIngest({ size: Number(e.target.value) })} />
            </FormField>
            <FormField id="set-overlap" label="Overlap (tokens)" hint="Smaller than the piece size." error={sizeErrors.overlap}>
              <Input id="set-overlap" type="number" className="w-32 bg-background tabular-nums" value={d.ingest.overlap} aria-invalid={!!sizeErrors.overlap} onChange={(e) => setIngest({ overlap: Number(e.target.value) })} />
            </FormField>
          </div>
          <SwitchRow id="set-headers" label="Context headers" hint="Each piece starts with the document title and heading path." checked={has('context_headers')} onChange={(v) => toggle('context_headers', v)} />
          {splitter !== 'fixed' && (
            <SwitchRow id="set-parent" label="Parent and child" hint="Small child pieces are searched; a match returns and cites the whole parent piece." checked={has('parent_child')} onChange={(v) => toggle('parent_child', v)}>
              {has('parent_child') && (
                <FormField id="set-child" label="Child size (tokens)" error={sizeErrors.childSize} className="mt-2">
                  <Input id="set-child" type="number" className="w-32 bg-background tabular-nums" value={d.ingest.childSize} aria-invalid={!!sizeErrors.childSize} onChange={(e) => setIngest({ childSize: Number(e.target.value) })} />
                </FormField>
              )}
            </SwitchRow>
          )}
        </div>
      </SettingsSection>

      <SettingsSection title="Questions and FAQs" description={`AI steps call ${d.ingest.model} at each sync, for changed pieces only.`}>
        <div className="flex flex-col gap-4">
          <SwitchRow id="set-faq" label="Likely questions" hint="A model writes questions each piece answers. They are searched; the piece is returned and cited. No review needed." checked={has('faq')} onChange={(v) => toggle('faq', v)}>
            {has('faq') && (
              <div className="mt-2 flex items-center gap-2 text-sm">
                <Select value={String(d.ingest.questionsPerSection)} onValueChange={(v) => setIngest({ questionsPerSection: Number(v) })}>
                  <SelectTrigger className="h-8 w-20 bg-background" aria-label="Questions per piece">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-muted-foreground">a piece</span>
              </div>
            )}
          </SwitchRow>
          <SwitchRow id="set-faq-pairs" label="FAQ drafts" hint="A model drafts question-and-answer pairs. Each waits in Changes for a person to approve, and cites its passage." checked={has('faq_pairs')} onChange={(v) => toggle('faq_pairs', v)} />

          {savedAi && (
            <div className="rounded-md border bg-background p-3" data-testid="ai-estimate">
              <div className="mb-2 text-sm font-medium">Cost estimate</div>
              {estimate.isPending ? (
                <p className="text-sm text-muted-foreground">Estimating…</p>
              ) : estimate.isError ? (
                <p className="text-sm text-destructive-text">Couldn’t estimate: {estimate.error.message}</p>
              ) : (
                <>
                  <FieldRow label="Sample" value={`${count(estimate.data.sampledItems)} of ${plural(estimate.data.totalItems, 'item')}`} />
                  <FieldRow label="Whole source" value={`about ${plural(estimate.data.calls, 'model call')} · ${count(estimate.data.inputTokens)} tokens in · ${count(estimate.data.outputTokens.low)} to ${count(estimate.data.outputTokens.high)} tokens out`} />
                  <FieldRow label="Model" value={estimate.data.model} />
                  <p className="mt-2 text-xs text-muted-foreground">{estimate.data.basis}</p>
                </>
              )}
              {dirty && changed.includes('ingest') && <p className="mt-2 text-xs text-muted-foreground">The estimate is for the saved settings; save to see the new one.</p>}
            </div>
          )}

          {approval.status === 'pending' ? (
            <Alert data-testid="ai-approval">
              <ShieldCheck className="size-4" />
              <AlertTitle>Approve AI steps</AlertTitle>
              <AlertDescription className="flex flex-col items-start gap-2">
                <p>Likely questions and FAQ drafts call a model at each sync. The knowledge owner approves them once, with this estimate in view. Until then syncs run without them.</p>
                <LoadingButton size="sm" isLoading={decide.isPending} onClick={() => decideSteps('approve')} data-testid="approve-ai-steps">
                  Approve AI steps
                </LoadingButton>
              </AlertDescription>
            </Alert>
          ) : approval.status === 'approved' ? (
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
              <span>
                Approved{approval.decidedBy ? ` by ${approval.decidedBy}` : ''}
                {approval.decidedAt ? ` · ${dateTime(approval.decidedAt)}` : ''}
              </span>
              <LoadingButton size="sm" variant="ghost" isLoading={decide.isPending} onClick={() => decideSteps('revoke')}>
                Take approval back
              </LoadingButton>
            </div>
          ) : null}
        </div>
      </SettingsSection>

      <SettingsSection title="Rules and metadata" description={web ? 'Which pages a sync takes in. Changing them updates the next sync.' : 'Any include rule admits an item; exclude rules win.'}>
        {Object.keys(ruleInputs).length > 0 ? (
          <SourceValuesForm idPrefix="set-web" inputs={ruleInputs} values={d.values} onChange={(v) => set('values', v)} errors={valuesErrors} />
        ) : (
          <div className="flex flex-col gap-2">
            {d.rules.length === 0 && <p className="text-sm text-muted-foreground">No rules. Every item in scope is indexed.</p>}
            {d.rules.map((r, i) => (
              <div key={r.id} className="flex flex-wrap items-center gap-2">
                <Select value={r.kind} onValueChange={(v) => setRule(i, { kind: v as Rule['kind'] })}>
                  <SelectTrigger className="h-8 w-28 bg-background" aria-label="Include or exclude">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="include">Include</SelectItem>
                    <SelectItem value="exclude">Exclude</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={r.field} onValueChange={(v) => setRule(i, { field: v as Rule['field'] })}>
                  <SelectTrigger className="h-8 w-40 bg-background" aria-label="Field">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RULE_FIELDS.map((f) => (
                      <SelectItem key={f.value} value={f.value}>
                        {f.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input className="h-8 min-w-36 flex-1 bg-background font-mono text-xs" value={r.value} aria-label="Value" placeholder={RULE_PLACEHOLDER[r.field]} onChange={(e) => setRule(i, { value: e.target.value })} />
                <Button variant="ghost" size="icon" className="size-8" onClick={() => set('rules', d.rules.filter((_, j) => j !== i))} aria-label="Remove rule">
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" className="w-fit" onClick={() => set('rules', [...d.rules, { id: `r${Date.now()}`, kind: 'exclude', field: 'path', value: '' }])}>
              <Plus className="size-3.5" /> Add rule
            </Button>
          </div>
        )}
        <div className="flex flex-col gap-2 pt-4">
          <span className="text-sm font-medium">Metadata</span>
          <MetadataMappingEditor value={d.metadataMapping} onChange={(v) => set('metadataMapping', v)} model={d.ingest.model} required={source.requiredMetadata} />
        </div>
      </SettingsSection>

      <SettingsSection title="Schedule" description="Unchanged items are checked with their own change signals and cost no model calls.">
        <SchedulePicker id="set-schedule" value={d.schedule} onChange={(v) => set('schedule', v)} />
        <p className="pt-2 text-xs text-muted-foreground">
          {source.status === 'paused' ? 'Paused: scheduled syncs are skipped.' : source.nextSyncAt ? `Next sync ${relativeTime(source.nextSyncAt)} · ${dateTime(source.nextSyncAt)}` : 'Syncs only when someone presses Sync now.'}
        </p>
      </SettingsSection>

      <DangerZone items={[{ title: 'Delete this source', description: `Removes ${plural(source.itemCount, 'item')}, the sync history and their pieces from every knowledge base that reads it.`, action: 'Delete source', onClick: onDelete, destructive: true }]} />

      <PageSaveActions dirty={dirty} saving={update.isPending} invalid={invalid} onSave={save} onDiscard={discard} testId="save-source-settings" />
    </div>
  );
}
