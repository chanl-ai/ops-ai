'use client';

import * as React from 'react';
import { Info, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { PARSING_OPTIONS, RULE_FIELDS, STRATEGIES, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { CopyButton } from '@/components/shared/copy-button';
import { DangerZone } from '@/components/shared/danger-zone';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useReprocessSource, useUpdateSource } from '@/hooks/knowledge-queries';
import { plural } from '@/lib/format';
import type { ChunkStrategy, Rule, Schedule, Sensitivity, SourceDetail, SourcePatch } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Draft = Required<Pick<SourcePatch, 'name' | 'scopeSummary' | 'parsing' | 'chunking' | 'rules' | 'metadataMapping' | 'tags' | 'titleFrom' | 'collection' | 'sensitivity' | 'permissions' | 'schedule' | 'deletedAtSource' | 'staleAfterDays' | 'notifyOnFailure'>>;

const pick = (s: SourceDetail): Draft => ({
  name: s.name,
  scopeSummary: s.scopeSummary,
  parsing: s.parsing,
  chunking: s.chunking,
  rules: s.rules,
  metadataMapping: s.metadataMapping,
  tags: s.tags,
  titleFrom: s.titleFrom,
  collection: s.collection,
  sensitivity: s.sensitivity,
  permissions: s.permissions,
  schedule: s.schedule,
  deletedAtSource: s.deletedAtSource,
  staleAfterDays: s.staleAfterDays,
  notifyOnFailure: s.notifyOnFailure,
});
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const scheduleFor = (kind: Schedule['kind']): Schedule =>
  kind === 'manual' ? { kind } : kind === 'daily' ? { kind, time: '02:00' } : kind === 'weekly' ? { kind, day: 'Mon', time: '03:00' } : kind === 'monthly' ? { kind, day: 1, time: '03:00' } : { kind: 'webhook', safetyNetDaily: true };

/** Every source setting on one page, saved together; parsing or chunking changes offer to reprocess. */
export function SourceSettingsTab({ source, onDelete }: { source: SourceDetail; onDelete: () => void }) {
  const update = useUpdateSource(source.id);
  const reprocess = useReprocessSource();
  const saved = React.useMemo(() => pick(source), [source]);
  const [d, setD] = React.useState<Draft>(saved);
  const [reprocessOpen, setReprocessOpen] = React.useState(false);
  React.useEffect(() => {
    setD(pick(source));
  }, [source.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = !same(d, saved);
  const meta = sourceTypeMeta(source.type);
  const nameError = d.name.trim().length < 2 || d.name.trim().length > 80 ? 'Name it in 2 to 80 characters.' : undefined;

  React.useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const setRule = (i: number, p: Partial<Rule>) => set('rules', d.rules.map((r, j) => (j === i ? { ...r, ...p } : r)));

  const save = async () => {
    if (nameError) return;
    const pipelineChanged = !same(d.parsing, saved.parsing) || !same(d.chunking, saved.chunking);
    const scopeChanged = !same(d.rules, saved.rules) || d.scopeSummary !== saved.scopeSummary;
    try {
      await update.mutateAsync(d);
      toast.success('Settings saved', { description: scopeChanged ? 'Scope or rules changed, so the next sync lists every item.' : undefined });
      if (pipelineChanged) setReprocessOpen(true);
    } catch (e) {
      toast.error('Couldn’t save settings', { description: (e as Error).message });
    }
  };
  const discard = () => {
    const before = d;
    setD(saved);
    toast('Changes discarded', { action: { label: 'Undo', onClick: () => setD(before) } });
  };

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <SettingsSection title="Connection and scope" description="What this source fetches">
        <div>
          <FieldRow label="Type" value={meta.label} />
          {source.connectionLabel && <FieldRow label="Connection" value={source.connectionLabel} mono />}
          <FieldRow label="Change detection" value={meta.changeDetection} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="set-name" label="Name" error={nameError}>
            <Input id="set-name" value={d.name} onChange={(e) => set('name', e.target.value)} aria-invalid={!!nameError} />
          </FormField>
          <FormField id="set-scope" label={meta.scopeLabel} hint="Changing scope makes the next sync list every item.">
            <Textarea id="set-scope" rows={2} value={d.scopeSummary} onChange={(e) => set('scopeSummary', e.target.value)} />
          </FormField>
        </div>
      </SettingsSection>

      <SettingsSection title="Parsing and chunking" description="How items become chunks. Changing these offers to reprocess every item.">
        <div className="grid gap-2 sm:grid-cols-2">
          {PARSING_OPTIONS.map((o) => (
            <div key={o.k} className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2">
              <Label htmlFor={`set-p-${o.k}`} className="flex items-center gap-1.5 font-normal">
                {o.label}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="size-3.5 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">{o.tip}</TooltipContent>
                </Tooltip>
              </Label>
              <Switch id={`set-p-${o.k}`} checked={d.parsing[o.k]} onCheckedChange={(v) => set('parsing', { ...d.parsing, [o.k]: v })} />
            </div>
          ))}
        </div>
        <RadioGroup value={d.chunking.strategy} onValueChange={(v) => set('chunking', { ...d.chunking, strategy: v as ChunkStrategy })} className="grid gap-2 sm:grid-cols-2" aria-label="Chunking strategy">
          {STRATEGIES.map((s) => (
            <label key={s.value} htmlFor={`set-st-${s.value}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border bg-background p-3', d.chunking.strategy === s.value && 'border-primary bg-primary/5')}>
              <RadioGroupItem value={s.value} id={`set-st-${s.value}`} className="mt-0.5" />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  {s.label}
                  {s.llm && (
                    <Badge variant="outline" className="font-normal">
                      Uses credits each sync
                    </Badge>
                  )}
                </span>
                <span className="block text-xs text-muted-foreground">{s.description}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
        <div className={cn('grid gap-6 sm:grid-cols-2', d.chunking.strategy === 'rows' && 'opacity-50')}>
          {(
            [
              ['size', 'Chunk size (tokens)', 100, 2000, 16],
              ['overlap', 'Overlap (tokens)', 0, 500, 10],
            ] as const
          ).map(([k, label, min, max, stepBy]) => (
            <div key={k} className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor={`set-c-${k}`}>{label}</Label>
                <Input
                  id={`set-c-${k}`}
                  type="number"
                  className="h-7 w-20 text-right tabular-nums"
                  min={min}
                  max={max}
                  value={d.chunking[k]}
                  disabled={d.chunking.strategy === 'rows'}
                  onChange={(e) => set('chunking', { ...d.chunking, [k]: Math.min(max, Math.max(min, Number(e.target.value) || min)) })}
                />
              </div>
              <Slider value={[d.chunking[k]]} min={min} max={max} step={stepBy} disabled={d.chunking.strategy === 'rows'} onValueChange={([v]) => set('chunking', { ...d.chunking, [k]: v })} aria-label={label} />
            </div>
          ))}
        </div>
      </SettingsSection>

      <SettingsSection title="Rules and metadata" description="Any include rule admits an item; exclude rules win. Changing rules makes the next sync list every item.">
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
            <Input className="h-8 min-w-36 flex-1 bg-background font-mono text-xs" value={r.value} aria-label="Value" placeholder="e.g. **/Archive/**" onChange={(e) => setRule(i, { value: e.target.value })} />
            <Button variant="ghost" size="icon" className="size-8" onClick={() => set('rules', d.rules.filter((_, j) => j !== i))} aria-label="Remove rule">
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
        <Button variant="outline" size="sm" className="w-fit" onClick={() => set('rules', [...d.rules, { id: `r${Date.now()}`, kind: 'exclude', field: 'path', value: '' }])}>
          <Plus className="size-3.5" /> Add rule
        </Button>
        <Label className="pt-2">Metadata mapping</Label>
        {d.metadataMapping.map((m, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Input className="h-8 w-40 bg-background font-mono text-xs" value={m.key} aria-label="Metadata key" onChange={(e) => set('metadataMapping', d.metadataMapping.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
            <span className="text-muted-foreground">←</span>
            <Input className="h-8 min-w-40 flex-1 bg-background font-mono text-xs" value={m.from} aria-label="Comes from" placeholder="e.g. field:Dept or static:en" onChange={(e) => set('metadataMapping', d.metadataMapping.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)))} />
            <Button variant="ghost" size="icon" className="size-8" onClick={() => set('metadataMapping', d.metadataMapping.filter((_, j) => j !== i))} aria-label="Remove mapping">
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
        <Button variant="outline" size="sm" className="w-fit" onClick={() => set('metadataMapping', [...d.metadataMapping, { key: '', from: 'static:' }])}>
          <Plus className="size-3.5" /> Add mapping
        </Button>
        <div className="grid gap-4 pt-2 sm:grid-cols-2">
          <FormField id="set-tags" label="Tags on every item" optional>
            <TagInput id="set-tags" value={d.tags} onChange={(v) => set('tags', v)} placeholder="e.g. policy" />
          </FormField>
          <FormField id="set-title" label="Title from">
            <Select value={d.titleFrom} onValueChange={(v) => set('titleFrom', v as Draft['titleFrom'])}>
              <SelectTrigger id="set-title" className="w-full bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="source">Title at the source</SelectItem>
                <SelectItem value="heading">First heading</SelectItem>
                <SelectItem value="filename">Filename</SelectItem>
              </SelectContent>
            </Select>
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
        </div>
      </SettingsSection>

      <SettingsSection title="Permissions and schedule" description="Who can see its items and when it syncs">
        <RadioGroup
          value={d.permissions.mode}
          onValueChange={(v) => set('permissions', v === 'selected' ? { mode: 'selected', principals: [] } : { mode: v as 'inherit' | 'workspace' })}
          className="grid gap-2"
          aria-label="Permissions"
        >
          {meta.supportsInherit && (
            <label htmlFor="set-pm-inherit" className={cn('flex cursor-pointer items-start gap-3 rounded-md border bg-background p-3', d.permissions.mode === 'inherit' && 'border-primary bg-primary/5')}>
              <RadioGroupItem value="inherit" id="set-pm-inherit" className="mt-0.5" />
              <span>
                <span className="block text-sm font-medium">Inherit from {meta.short}</span>
                <span className="block text-xs text-muted-foreground">Each item keeps its own permissions.</span>
              </span>
            </label>
          )}
          <label htmlFor="set-pm-ws" className={cn('flex cursor-pointer items-start gap-3 rounded-md border bg-background p-3', d.permissions.mode === 'workspace' && 'border-primary bg-primary/5')}>
            <RadioGroupItem value="workspace" id="set-pm-ws" className="mt-0.5" />
            <span>
              <span className="block text-sm font-medium">Workspace-wide</span>
              <span className="block text-xs text-muted-foreground">Every agent and member that can query a knowledge base sees these items.</span>
            </span>
          </label>
          <label htmlFor="set-pm-sel" className={cn('flex cursor-pointer items-start gap-3 rounded-md border bg-background p-3', d.permissions.mode === 'selected' && 'border-primary bg-primary/5')}>
            <RadioGroupItem value="selected" id="set-pm-sel" className="mt-0.5" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium">Selected members and groups</span>
              {d.permissions.mode === 'selected' && (
                <span className="mt-2 block">
                  <TagInput value={d.permissions.principals} onChange={(v) => set('permissions', { mode: 'selected', principals: v })} placeholder="e.g. group:Lending" />
                </span>
              )}
            </span>
          </label>
        </RadioGroup>
        <Label className="pt-2">Refresh schedule</Label>
        <RadioGroup value={d.schedule.kind} onValueChange={(v) => set('schedule', scheduleFor(v as Schedule['kind']))} className="flex flex-wrap gap-2" aria-label="Refresh schedule">
          {(['manual', 'daily', 'weekly', 'monthly', 'webhook'] as const).map((k) => (
            <label key={k} htmlFor={`set-sc-${k}`} className={cn('flex cursor-pointer items-center gap-2 rounded-md border bg-background px-3 py-1.5 text-sm', d.schedule.kind === k && 'border-primary bg-primary/5', k === 'webhook' && !meta.supportsWebhook && 'cursor-not-allowed opacity-50')}>
              <RadioGroupItem value={k} id={`set-sc-${k}`} disabled={k === 'webhook' && !meta.supportsWebhook} />
              {{ manual: 'Manual', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly', webhook: 'When the source changes' }[k]}
            </label>
          ))}
        </RadioGroup>
        {d.schedule.kind === 'daily' && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">At</span>
            <Input type="time" className="h-8 w-32 bg-background" value={d.schedule.time} onChange={(e) => set('schedule', { kind: 'daily', time: e.target.value })} aria-label="Time" />
          </div>
        )}
        {d.schedule.kind === 'weekly' &&
          (() => {
            const w = d.schedule;
            return (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Select value={w.day} onValueChange={(v) => set('schedule', { ...w, day: v })}>
                  <SelectTrigger className="h-8 w-28 bg-background" aria-label="Day">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((x) => (
                      <SelectItem key={x} value={x}>
                        {x}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input type="time" className="h-8 w-32 bg-background" value={w.time} onChange={(e) => set('schedule', { ...w, time: e.target.value })} aria-label="Time" />
              </div>
            );
          })()}
        {d.schedule.kind === 'monthly' &&
          (() => {
            const m = d.schedule;
            return (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Day</span>
                <Input type="number" min={1} max={28} className="h-8 w-20 bg-background" value={m.day} onChange={(e) => set('schedule', { ...m, day: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })} aria-label="Day of month" />
                <Input type="time" className="h-8 w-32 bg-background" value={m.time} onChange={(e) => set('schedule', { ...m, time: e.target.value })} aria-label="Time" />
              </div>
            );
          })()}
        {d.schedule.kind === 'webhook' &&
          (() => {
            const wh = d.schedule;
            const url = `https://api.northfieldbank.com/ops/hooks/sources/${source.id}`;
            return (
              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate font-mono text-xs">{url}</code>
                  <CopyButton text={url} variant="outline" />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <Label htmlFor="set-safety" className="font-normal">
                    Also run daily as a safety net
                  </Label>
                  <Switch id="set-safety" checked={wh.safetyNetDaily} onCheckedChange={(v) => set('schedule', { kind: 'webhook', safetyNetDaily: v })} />
                </div>
              </div>
            );
          })()}
        <div className="grid gap-4 pt-2 sm:grid-cols-2">
          <FormField id="set-deleted" label="When an item is deleted at the source">
            <Select value={d.deletedAtSource} onValueChange={(v) => set('deletedAtSource', v as Draft['deletedAtSource'])}>
              <SelectTrigger id="set-deleted" className="w-full bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="remove">Remove it from the index</SelectItem>
                <SelectItem value="keep_stale">Keep it and mark it stale</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="set-stale" label="Stale after (days)" hint="Past this, items are flagged for their owner to review.">
            <Input id="set-stale" type="number" min={1} className="bg-background" value={d.staleAfterDays} onChange={(e) => set('staleAfterDays', Math.max(1, Number(e.target.value) || 1))} />
          </FormField>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2">
          <Label htmlFor="set-notify" className="font-normal">
            Notify the owner when a sync fails
          </Label>
          <Switch id="set-notify" checked={d.notifyOnFailure} onCheckedChange={(v) => set('notifyOnFailure', v)} />
        </div>
      </SettingsSection>

      <DangerZone items={[{ title: 'Delete this source', description: `Removes ${plural(source.itemCount, 'item')}, the sync history and their chunks from every knowledge base that reads it.`, action: 'Delete source', onClick: onDelete, destructive: true }]} />

      {dirty && (
        <div data-unsaved-bar className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur">
          <span className="text-sm text-muted-foreground">Unsaved changes</span>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={discard} disabled={update.isPending}>
              <RotateCcw className="size-3.5" /> Discard
            </Button>
            <LoadingButton size="sm" isLoading={update.isPending} disabled={!!nameError} onClick={save}>
              Save changes
            </LoadingButton>
          </div>
        </div>
      )}

      <DialogShell
        open={reprocessOpen}
        onOpenChange={setReprocessOpen}
        size="sm"
        title={`Reprocess all ${plural(source.itemCount, 'item')} now?`}
        description="Parsing or chunking changed. Existing chunks were built with the old settings; otherwise items update only when a sync next touches them."
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button
              variant="outline"
              disabled={update.isPending || reprocess.isPending}
              onClick={async () => {
                await update.mutateAsync({ reprocessPending: true });
                setReprocessOpen(false);
                toast.message('Reprocess pending', { description: 'Items update as syncs touch them.' });
              }}
            >
              Not now
            </Button>
            <LoadingButton
              isLoading={reprocess.isPending}
              onClick={() =>
                reprocess.mutate(source.id, {
                  onSuccess: () => {
                    setReprocessOpen(false);
                    toast.success(`Reprocessing every item in ${source.name}`);
                  },
                  onError: (e) => toast.error('Couldn’t start reprocessing', { description: e.message }),
                })
              }
            >
              Reprocess now
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">Reprocessing runs as a full sync. Knowledge bases pick up the new chunks on their next refresh.</p>
      </DialogShell>
    </div>
  );
}
