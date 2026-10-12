'use client';

import * as React from 'react';
import { Plus, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { ConnectionChip } from '@/components/integrations/integration-meta';
import { RULE_FIELDS, RULE_PLACEHOLDER, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { IngestForm } from '@/components/sources/ingest-form';
import { MetadataMappingEditor } from '@/components/sources/metadata-mapping-editor';
import { SplitPreviewPanel } from '@/components/sources/split-preview';
import { CopyButton } from '@/components/shared/copy-button';
import { DangerZone } from '@/components/shared/danger-zone';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useIngestSamples, usePreviewSplit, useUpdateSource } from '@/hooks/knowledge-queries';
import { plural } from '@/lib/format';
import type { Rule, Schedule, Sensitivity, SourceDetail, SourcePatch } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Draft = Required<Pick<SourcePatch, 'name' | 'scopeSummary' | 'parsing' | 'ingest' | 'rules' | 'metadataMapping' | 'tags' | 'titleFrom' | 'collection' | 'sensitivity' | 'permissions' | 'schedule' | 'deletedAtSource' | 'staleAfterDays' | 'notifyOnFailure'>>;

const pick = (s: SourceDetail): Draft => ({
  name: s.name,
  scopeSummary: s.scopeSummary,
  parsing: s.parsing,
  ingest: s.ingest,
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

/** Every source setting on one page, saved together; ingestion changes mark the source for a re-index. */
export function SourceSettingsTab({ source, onDelete }: { source: SourceDetail; onDelete: () => void }) {
  const update = useUpdateSource(source.id);
  const samples = useIngestSamples(source.id);
  const previewSplit = usePreviewSplit();
  const saved = React.useMemo(() => pick(source), [source]);
  const [d, setD] = React.useState<Draft>(saved);
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
    const pipelineChanged = !same(d.parsing, saved.parsing) || !same(d.ingest, saved.ingest) || !same(d.metadataMapping, saved.metadataMapping);
    const rulesChanged = !same(d.rules, saved.rules);
    try {
      await update.mutateAsync(d);
      toast.success('Settings saved', {
        description: pipelineChanged ? 'Chunks were built with the old ingestion settings. Re-index from the banner to apply them.' : rulesChanged ? 'Rules apply now: matching items are excluded, and items they no longer exclude wait for the next sync.' : undefined,
      });
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
          {source.connection && <FieldRow label="Connection" value={<ConnectionChip connection={source.connection} />} />}
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

      <SettingsSection title="Ingestion" description="How items become chunks. Saving a change marks the source for a re-index; the preview shows the result first.">
        <IngestForm idPrefix="set" ingest={d.ingest} parsing={d.parsing} onIngest={(v) => set('ingest', v)} onParsing={(v) => set('parsing', v)} showApproval />
        <SplitPreviewPanel
          idPrefix="set"
          samples={samples.data ?? []}
          samplesLoading={samples.isPending}
          ingest={d.ingest}
          parsing={d.parsing}
          mapping={d.metadataMapping}
          onPreview={(input) => previewSplit.mutateAsync(input)}
        />
      </SettingsSection>

      <SettingsSection title="Rules and metadata" description="Any include rule admits an item; exclude rules win. Rules apply when saved.">
        {d.rules.length === 0 && <p className="text-sm text-muted-foreground">No rules. Every item in scope is indexed.</p>}
        {source.governance.excluded > 0 && (
          <p className="text-xs text-muted-foreground">
            {plural(source.governance.excluded, 'item')} excluded now; the Items tab names the rule for each.
          </p>
        )}
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
        <Label className="pt-2">Metadata</Label>
        <MetadataMappingEditor value={d.metadataMapping} onChange={(v) => set('metadataMapping', v)} model={d.ingest.model} required={source.requiredMetadata} />
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

    </div>
  );
}
