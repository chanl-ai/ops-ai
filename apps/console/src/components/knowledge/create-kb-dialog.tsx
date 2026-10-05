'use client';

import * as React from 'react';
import { AlertTriangle, Pencil } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { KeyValues } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { count, plural, relativeTime } from '@/lib/format';
import type { KnowledgeBaseInput, RetrievalPreset, SourceRow } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

import { KB_COLORS, KbDot, RunStatusBadge, SourceTypeIcon, sourceTypeMeta } from './knowledge-meta';

const STEPS = ['Basics', 'Sources', 'Retrieval preset', 'Review'] as const;

const PRESETS: { value: RetrievalPreset; label: string; description: string }[] = [
  { value: 'balanced', label: 'Balanced', description: 'Hybrid search, rerank on, 8 chunks, threshold 0.50, answer synthesis on. A good default for policy and product content.' },
  { value: 'precise', label: 'Precise', description: 'Hybrid, rerank on, 5 chunks, threshold 0.65, temperature 0. Fewer answers, fewer wrong ones. For fees, limits and regulated wording.' },
  { value: 'raw', label: 'Raw retrieval', description: 'Hybrid, rerank off, 10 chunks, threshold 0.40, no synthesis. Returns chunks only, for an agent to answer from.' },
];

const initial = (): KnowledgeBaseInput => ({ name: '', description: '', color: 'teal', sourceIds: [], preset: 'balanced', collections: [] });

/** New knowledge base in four steps; on create the page opens it so the first index build can be watched. */
export function CreateKbDialog({
  open,
  onOpenChange,
  sources,
  existingNames,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sources: SourceRow[];
  existingNames: string[];
  onSubmit: (input: KnowledgeBaseInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [step, setStep] = React.useState(1);
  const [v, setV] = React.useState<KnowledgeBaseInput>(initial);
  const [touched, setTouched] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (open) {
      setStep(1);
      setV(initial());
      setTouched(false);
      setSubmitError(null);
    }
  }, [open]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  const set = <K extends keyof KnowledgeBaseInput>(k: K, val: KnowledgeBaseInput[K]) => setV((s) => ({ ...s, [k]: val }));
  const toggle = (sid: string) => set('sourceIds', v.sourceIds.includes(sid) ? v.sourceIds.filter((x) => x !== sid) : [...v.sourceIds, sid]);
  const allCollections = Array.from(new Set(sources.map((s) => s.collection))).sort();
  const picked = sources.filter((s) => v.sourceIds.includes(s.id));
  const neverSynced = picked.filter((s) => !s.lastSyncAt);
  const errors = {
    name:
      v.name.trim().length < 2 || v.name.length > 80
        ? 'Name it in 2 to 80 characters, e.g. Card disputes.'
        : existingNames.some((n) => n.toLowerCase() === v.name.trim().toLowerCase())
          ? 'A knowledge base with this name already exists.'
          : undefined,
    description: v.description.length > 500 ? 'Keep the description under 500 characters.' : undefined,
    sources: v.sourceIds.length ? undefined : 'Pick at least one source.',
  };
  const err = (k: keyof typeof errors) => (touched ? errors[k] : undefined);
  const stepValid = step === 1 ? !errors.name && !errors.description : step === 2 ? !errors.sources : true;
  const next = () => {
    if (!stepValid) return setTouched(true);
    setTouched(false);
    setStep(step + 1);
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New knowledge base"
      description={`Step ${step} of ${STEPS.length} · ${STEPS[step - 1]}`}
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="kb-stepper" />}
      bodyRef={bodyRef}
      bodyClassName="h-[26rem]"
      footer={
        <div className="flex w-full justify-between gap-2">
          <Button variant="ghost" onClick={() => (step === 1 ? onOpenChange(false) : setStep(step - 1))} disabled={isPending}>
            {step === 1 ? 'Cancel' : 'Back'}
          </Button>
          {step < STEPS.length ? (
            <Button onClick={next}>Next</Button>
          ) : (
            <LoadingButton
              isLoading={isPending}
              loadingText="Creating…"
              onClick={async () => {
                try {
                  await onSubmit({ ...v, name: v.name.trim(), description: v.description.trim() });
                  onOpenChange(false);
                } catch (e) {
                  setSubmitError((e as Error).message);
                }
              }}
            >
              Create and build index
            </LoadingButton>
          )}
        </div>
      }
    >
      {step === 1 && (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            next();
          }}
        >
          <FormField id="kb-name" label="Name" error={err('name')}>
            <Input id="kb-name" value={v.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Card disputes" autoFocus aria-invalid={!!err('name')} />
          </FormField>
          <FormField id="kb-desc" label="Description" optional hint={`${v.description.length} / 500 · agents see this when choosing what to search.`} error={err('description')}>
            <Textarea id="kb-desc" rows={3} value={v.description} onChange={(e) => set('description', e.target.value)} placeholder="e.g. Dispute reason codes, chargeback timelines and provisional credit rules" aria-invalid={!!err('description')} />
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="kb-color" label="Colour">
              <Select value={v.color} onValueChange={(c) => set('color', c)}>
                <SelectTrigger id="kb-color" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.keys(KB_COLORS).map((c) => (
                    <SelectItem key={c} value={c}>
                      <span className="flex items-center gap-2">
                        <KbDot color={c} /> <span className="capitalize">{c}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="kb-collections" label="Collections it may read" optional hint="Department boundaries. Empty means the collections of its sources.">
              <TagInput id="kb-collections" value={v.collections} onChange={(c) => set('collections', c)} suggestions={allCollections} placeholder="All collections" />
            </FormField>
          </div>
          <button type="submit" hidden />
        </form>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">{v.sourceIds.length ? `${plural(v.sourceIds.length, 'source')} selected` : 'Pick the sources this knowledge base reads.'}</p>
          {err('sources') && <p className="text-xs text-destructive">{err('sources')}</p>}
          {sources.length === 0 ? (
            <p className="rounded-md border p-6 text-center text-sm text-muted-foreground">No sources yet. Add one from Sources first; a source is how content gets in.</p>
          ) : (
            <div className="divide-y rounded-md border">
              {sources.map((s) => (
                <label key={s.id} htmlFor={`kb-src-${s.id}`} className={cn('flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-accent/40', v.sourceIds.includes(s.id) && 'bg-primary/5')}>
                  <Checkbox id={`kb-src-${s.id}`} checked={v.sourceIds.includes(s.id)} onCheckedChange={() => toggle(s.id)} />
                  <SourceTypeIcon type={s.type} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{s.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {sourceTypeMeta(s.type).label} · {s.collection} · {plural(s.itemsIndexed, 'item')}
                    </span>
                  </span>
                  <span className="hidden items-center gap-2 sm:flex">
                    <RunStatusBadge status={s.running ? 'running' : s.lastRunStatus} />
                    <span className="text-xs text-muted-foreground">{relativeTime(s.lastSyncAt)}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          {neverSynced.length > 0 && (
            <p className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              {neverSynced.map((s) => s.name).join(', ')} {neverSynced.length === 1 ? 'has' : 'have'} never synced. The knowledge base stays empty until the first sync finishes.
            </p>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-3">
          <RadioGroup value={v.preset} onValueChange={(p) => set('preset', p as RetrievalPreset)} className="grid gap-2">
            {PRESETS.map((p) => (
              <label key={p.value} htmlFor={`kb-preset-${p.value}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', v.preset === p.value && 'border-primary bg-primary/5')}>
                <RadioGroupItem value={p.value} id={`kb-preset-${p.value}`} className="mt-0.5" />
                <span>
                  <span className="block text-sm font-medium">{p.label}</span>
                  <span className="block text-xs text-muted-foreground">{p.description}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
          <p className="text-xs text-muted-foreground">Every setting can be changed later on the Retrieval tab.</p>
        </div>
      )}

      {step === 4 && (
        <div className="flex flex-col gap-4">
          {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
          {(
            [
              ['Basics', 1, [['Name', <span key="n" className="flex items-center gap-2"><KbDot color={v.color} /> {v.name}</span>], ['Description', v.description], ['Collections', v.collections.join(', ') || 'Collections of its sources']]],
              ['Sources', 2, [['Sources', picked.map((s) => s.name).join(', ')], ['Documents', count(picked.reduce((n, s) => n + s.itemsIndexed, 0))]]],
              ['Retrieval preset', 3, [['Preset', PRESETS.find((p) => p.value === v.preset)?.label]]],
            ] as [string, number, [string, React.ReactNode][]][]
          ).map(([title, target, rows]) => (
            <div key={title} className="rounded-lg border">
              <div className="flex items-center justify-between border-b px-3 py-2">
                <Label className="text-sm font-medium">{title}</Label>
                <Button variant="ghost" size="sm" onClick={() => setStep(target)}>
                  <Pencil className="size-3.5" /> Edit
                </Button>
              </div>
              <div className="px-3">
                <KeyValues rows={rows} />
              </div>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">The first index build starts when you create it. Agents can cite it once it finishes.</p>
        </div>
      )}
    </DialogShell>
  );
}
