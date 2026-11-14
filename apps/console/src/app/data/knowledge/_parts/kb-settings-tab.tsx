'use client';

import * as React from 'react';
import Link from 'next/link';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm, type Control, type FieldPath } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { EntityPicker } from '@/components/shared/entity-picker';
import { FormField } from '@/components/shared/form-field';
import { PageSaveActions } from '@/components/shared/page-save-actions';
import { SettingsField, SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useUpdateKb } from '@/hooks/knowledge-queries';
import { peopleOptions } from '@/hooks/options-queries';
import { count } from '@/lib/format';
import type { KnowledgeBaseDetail, KnowledgeBasePatch, BaseSourceDefaults } from '@/lib/types/knowledge';

const MODES = [
  { value: 'hybrid', label: 'Meaning and keyword', hint: 'Both lanes, fused by rank. Keyword only while pieces are being embedded.' },
  { value: 'meaning', label: 'Meaning only', hint: 'Pieces close in meaning to the question.' },
  { value: 'keyword', label: 'Keyword only', hint: 'Pieces that share the question’s words.' },
] as const;
const SPLITS = [
  { value: 'structure', label: 'At headings', hint: 'Sections split at headings; a long one splits at sentences.' },
  { value: 'fixed', label: 'Fixed size', hint: 'Equal windows of tokens with overlap, ignoring headings.' },
  { value: 'table_rows', label: 'Table rows', hint: 'One piece per table row, for rate and fee tables.' },
] as const;
const MIN_SIZE = 100;
const MAX_SIZE = 2000;
const LIMIT_MAX = 20;
const unit = z.number({ error: 'Between 0 and 1.' }).min(0, 'Between 0 and 1.').max(1, 'Between 0 and 1.');
const whole = (min: number, max: number, message: string) => z.number({ error: message }).int(message).min(min, message).max(max, message);

/** Every section's fields as one form; kb-service checks the same bounds on save (schemas.py `_Section`). */
const schema = z
  .object({
    chunking: z.object({
      split: z.enum(['structure', 'fixed', 'table_rows']),
      size: whole(MIN_SIZE, MAX_SIZE, `${MIN_SIZE} to ${count(MAX_SIZE)} tokens.`),
      overlap: z.number().int('A whole number.').min(0, 'Zero or more.'),
      contextHeaders: z.boolean(),
      parentChild: z.boolean(),
      childSize: z.number().int('A whole number.').min(1, 'More than zero.'),
      clean: z.boolean(),
    }),
    search: z.object({
      searchMode: z.enum(['hybrid', 'meaning', 'keyword']),
      hybridWeight: unit,
      threshold: unit,
      meaningThreshold: unit,
      chunkLimit: whole(1, LIMIT_MAX, `A whole number from 1 to ${LIMIT_MAX}.`),
      scopeCollections: z.array(z.string()),
      scopeSourceIds: z.array(z.string()),
      tagsInclude: z.array(z.string()),
      tagsExclude: z.array(z.string()),
      includeUntagged: z.boolean(),
      conditionKey: z.string(),
      conditionValue: z.string().max(500, 'At most 500 characters.'),
      rerank: z.boolean(),
      rewrite: z.boolean(),
      rewriteInstructions: z.string().max(1000, 'At most 1,000 characters.'),
      queryModel: z.string(),
    }),
    answer: z.object({
      shape: z.enum(['answer_with_citations', 'chunks']),
      withholdUncited: z.boolean(),
      noAnswerMessage: z.string().trim().min(1, 'Say what the agent answers when nothing is found.').max(500, 'At most 500 characters.'),
    }),
    sync: z.object({
      changes: z.enum(['apply', 'review']),
      removedAtSource: z.enum(['remove', 'keep']),
      staleAfterDays: whole(1, 3650, 'A whole number of days from 1 to 3,650.'),
      notifyOnFailure: z.boolean(),
    }),
    access: z.object({
      owner: z.string().min(1, 'Choose the owner.'),
      mcpEnabled: z.boolean(),
      toolName: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/, 'Lowercase letters, digits and underscores, starting with a letter; at most 64.'),
    }),
  })
  .refine((v) => v.chunking.overlap < v.chunking.size, { message: 'Smaller than the piece size.', path: ['chunking', 'overlap'] })
  .refine((v) => !v.chunking.parentChild || v.chunking.childSize < v.chunking.size, { message: 'Child pieces are smaller than the piece size.', path: ['chunking', 'childSize'] })
  .refine((v) => !v.search.conditionKey || v.search.conditionValue.trim().length > 0, { message: 'Enter the value the field must equal.', path: ['search', 'conditionValue'] });
type Values = z.infer<typeof schema>;

/** The stored sections as the form's values. */
function valuesOf(kb: KnowledgeBaseDetail): Values {
  const r = kb.retrieval;
  const sd: BaseSourceDefaults = kb.sourceDefaults ?? { strategies: ['structure', 'context_headers'] as BaseSourceDefaults['strategies'], size: 400, overlap: 40, childSize: 120 };
  const first = r.filters?.conditions?.[0];
  return {
    chunking: {
      split: sd.strategies.includes('table_rows') ? 'table_rows' : sd.strategies.includes('fixed') ? 'fixed' : 'structure',
      size: sd.size,
      overlap: sd.overlap,
      contextHeaders: sd.strategies.includes('context_headers'),
      parentChild: sd.strategies.includes('parent_child'),
      childSize: sd.childSize,
      clean: sd.strategies.includes('clean'),
    },
    search: {
      searchMode: MODES.some((m) => m.value === r.searchMode) ? (r.searchMode as Values['search']['searchMode']) : 'hybrid',
      hybridWeight: r.hybridWeight,
      threshold: r.threshold,
      meaningThreshold: r.meaningThreshold ?? 0.38,
      chunkLimit: r.chunkLimit,
      scopeCollections: r.scopeCollections ?? [],
      scopeSourceIds: r.scopeSourceIds ?? [],
      tagsInclude: r.tagsInclude ?? [],
      tagsExclude: r.tagsExclude ?? [],
      includeUntagged: r.includeUntagged ?? true,
      conditionKey: first && first.op === 'is' ? first.key : '',
      conditionValue: first && first.op === 'is' ? first.value : '',
      rerank: !!r.rerank,
      rewrite: r.rewrite === 'rewrite',
      rewriteInstructions: r.rewriteInstructions ?? '',
      queryModel: r.queryModel ?? '',
    },
    answer: kb.answer ?? { shape: 'answer_with_citations', withholdUncited: true, noAnswerMessage: 'I could not find that in the knowledge base.' },
    sync: kb.sync ?? { changes: 'apply', removedAtSource: 'remove', staleAfterDays: 365, notifyOnFailure: true },
    access: { owner: kb.owner ?? '', mcpEnabled: !!kb.access.mcp?.enabled, toolName: kb.access.mcp?.toolName ?? '' },
  };
}

/** The sections that changed, as kb-service merges them: each section sent whole, the rest left out. */
function patchOf(kb: KnowledgeBaseDetail, before: Values, v: Values): KnowledgeBasePatch {
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const patch: KnowledgeBasePatch = {};
  if (!same(before.chunking, v.chunking)) {
    const c = v.chunking;
    const strategies: BaseSourceDefaults['strategies'] = [c.split];
    if (c.contextHeaders) strategies.push('context_headers');
    if (c.parentChild && c.split !== 'fixed') strategies.push('parent_child');
    if (c.clean) strategies.push('clean');
    patch.sourceDefaults = { strategies, size: c.size, overlap: c.overlap, childSize: c.childSize };
  }
  if (!same(before.search, v.search)) {
    const s = v.search;
    // Only the first "is" condition is edited here; any others the API holds are kept as they are.
    const held = kb.retrieval.filters?.conditions ?? [];
    const others = held.filter((c, i) => !(i === 0 && c.op === 'is'));
    const conditions = s.conditionKey ? [{ id: held[0]?.id ?? '', key: s.conditionKey, op: 'is' as const, value: s.conditionValue.trim() }, ...others] : others;
    patch.retrieval = {
      searchMode: s.searchMode,
      hybridWeight: s.hybridWeight,
      threshold: s.threshold,
      meaningThreshold: s.meaningThreshold,
      chunkLimit: s.chunkLimit,
      scopeCollections: s.scopeCollections,
      scopeSourceIds: s.scopeSourceIds,
      tagsInclude: s.tagsInclude,
      tagsExclude: s.tagsExclude,
      includeUntagged: s.includeUntagged,
      filters: { match: kb.retrieval.filters?.match ?? 'all', conditions },
      rerank: s.rerank,
      rewrite: s.rewrite ? 'rewrite' : 'off',
      rewriteInstructions: s.rewriteInstructions,
      queryModel: s.queryModel.trim(),
    };
  }
  if (!same(before.answer, v.answer)) patch.answer = { ...v.answer, noAnswerMessage: v.answer.noAnswerMessage.trim() };
  if (!same(before.sync, v.sync)) patch.sync = v.sync;
  if (before.access.owner !== v.access.owner) patch.owner = v.access.owner;
  if (before.access.mcpEnabled !== v.access.mcpEnabled || before.access.toolName !== v.access.toolName) patch.access = { mcp: { enabled: v.access.mcpEnabled, toolName: v.access.toolName } };
  return patch;
}

/**
 * Settings: every setting of a knowledge base in six sections. Chunking holds the defaults a new source copies;
 * Embedding is the installation's; Search, Answer and Sync apply to every search and sync of the base; Access names its
 * owner and whether it is offered as an MCP tool. A member sees it read-only (the page's BuilderFieldset). Saving sends
 * only the sections that changed, and kb-service merges each over what it holds.
 */
export function KbSettingsTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const update = useUpdateKb(kb.id);
  const saved = React.useMemo(() => valuesOf(kb), [kb]);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: saved, mode: 'onChange' });
  const { control, formState, watch, handleSubmit, reset } = form;
  React.useEffect(() => {
    reset(valuesOf(kb));
  }, [kb.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const v = watch();
  const err = (path: string) => path.split('.').reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], formState.errors) as { message?: string } | undefined;
  const sources = kb.attached.map((a) => ({ id: a.sourceId, name: a.source.name }));
  const sourceName = (id: string) => sources.find((s) => s.id === id)?.name ?? id;
  const collections = Array.from(new Set([...kb.collections, ...kb.attached.map((a) => a.source.collection).filter((c): c is string => !!c)]));

  const save = handleSubmit(async (values) => {
    const patch = patchOf(kb, saved, values);
    try {
      await update.mutateAsync(patch);
      reset(values);
      toast.success('Settings saved', { description: 'They apply to the next search and sync of this knowledge base.' });
    } catch (e) {
      toast.error('Couldn’t save the settings', { description: (e as Error).message });
    }
  });

  return (
    <form className="flex flex-col gap-4" data-testid="kb-settings" onSubmit={(e) => void save(e)}>
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <SettingsSection title="Chunking" description="Defaults for each new source of this base. A source keeps its own copy, changed on its Settings; changing these never re-splits a source.">
          <div className="flex flex-col gap-5">
            <FormField id="set-split" label="Split" hint={SPLITS.find((s) => s.value === v.chunking.split)?.hint}>
              <Controller control={control} name="chunking.split" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="set-split" className="w-60 bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>{SPLITS.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent>
                </Select>
              )} />
            </FormField>
            <div className="grid gap-4 sm:grid-cols-2">
              <NumberInput control={control} name="chunking.size" id="set-size" label="Piece size (tokens)" hint={`${MIN_SIZE} to ${count(MAX_SIZE)}.`} error={err('chunking.size')?.message} />
              <NumberInput control={control} name="chunking.overlap" id="set-overlap" label="Overlap (tokens)" hint="Smaller than the piece size." error={err('chunking.overlap')?.message} />
            </div>
            <SwitchField control={control} name="chunking.contextHeaders" id="set-headers" label="Context headers" description="Each piece starts with the document title and heading path." />
            {v.chunking.split !== 'fixed' && (
              <SwitchField control={control} name="chunking.parentChild" id="set-parent" label="Parent and child" description="Small child pieces are searched; a match returns and cites the whole parent piece." />
            )}
            {v.chunking.parentChild && v.chunking.split !== 'fixed' && (
              <NumberInput control={control} name="chunking.childSize" id="set-child" label="Child size (tokens)" error={err('chunking.childSize')?.message} />
            )}
          </div>
        </SettingsSection>

        <SettingsSection title="Embedding" description="One embedding model for the whole installation, so every base can be searched together.">
          {kb.embedding ? (
            <dl className="grid gap-4 sm:grid-cols-2" data-testid="kb-settings-embedding">
              <div>
                <dt className="text-sm font-medium">Model</dt>
                <dd className="text-sm">{kb.embedding.model} · {count(kb.embedding.width)} wide</dd>
              </div>
              <div>
                <dt className="text-sm font-medium">Pieces embedded</dt>
                <dd className="text-sm tabular-nums">{count(kb.embedding.embedded)} of {count(kb.embedding.units)}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">No embedding model is set up, so this base is searched by keyword only.</p>
          )}
          <p className="mt-4 text-xs text-muted-foreground">
            Changed by a workspace admin under <Link className="text-primary underline" href="/settings/workspace/model-providers">Settings › Models</Link>; a change embeds every piece again and reads no file again.
          </p>
        </SettingsSection>

        <SettingsSection title="Search" description="Applied to every search of this base: by agents, the query route, MCP and the Playground.">
          <div className="flex flex-col gap-5">
            <FormField id="set-mode" label="Mode" hint={MODES.find((m) => m.value === v.search.searchMode)?.hint}>
              <Controller control={control} name="search.searchMode" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="set-mode" className="w-60 bg-background" data-testid="kb-settings-mode"><SelectValue /></SelectTrigger>
                  <SelectContent>{MODES.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent>
                </Select>
              )} />
            </FormField>
            {v.search.searchMode === 'hybrid' && (
              <NumberSlider control={control} name="search.hybridWeight" id="set-weight" label="Weight toward meaning" hint="0 is keyword only, 1 is meaning only." error={err('search.hybridWeight')?.message} />
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <NumberSlider control={control} name="search.threshold" id="set-keyword-floor" label="Keyword floor" hint="Share of the question’s words a piece must hold." error={err('search.threshold')?.message} />
              <NumberSlider control={control} name="search.meaningThreshold" id="set-meaning-floor" label="Meaning floor" hint="How close in meaning a piece must be." error={err('search.meaningThreshold')?.message} />
            </div>
            <NumberInput control={control} name="search.chunkLimit" id="set-limit" label="Pieces returned" hint={`At most this many, and at most two from one document. 1 to ${LIMIT_MAX}.`} error={err('search.chunkLimit')?.message} />
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="set-collections" label="Collections searched" hint={collections.length ? `Empty searches every collection: ${collections.join(', ')}.` : 'Empty searches every collection.'}>
                <Controller control={control} name="search.scopeCollections" render={({ field }) => (
                  <TagInput id="set-collections" value={field.value} onChange={field.onChange} suggestions={collections} placeholder="All collections" validate={(c) => (collections.includes(c) ? undefined : 'Not a collection of this base.')} />
                )} />
              </FormField>
              <FormField id="set-sources" label="Sources searched" hint={`Empty searches all ${count(sources.length)} attached sources.`}>
                <Controller control={control} name="search.scopeSourceIds" render={({ field }) => (
                  <TagInput
                    id="set-sources"
                    value={field.value}
                    onChange={(next) => field.onChange(next.map((n) => sources.find((s) => s.name === n || s.id === n)?.id ?? n))}
                    suggestions={sources.map((s) => s.name)}
                    format={sourceName}
                    placeholder={`All ${count(sources.length)} attached sources`}
                    validate={(n) => (sources.some((s) => s.name === n || s.id === n) ? undefined : 'Not a source of this base.')}
                  />
                )} />
              </FormField>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="set-tags-in" label="Only documents tagged" hint="Empty searches every tag.">
                <Controller control={control} name="search.tagsInclude" render={({ field }) => <TagInput id="set-tags-in" value={field.value} onChange={field.onChange} placeholder="Any tag" />} />
              </FormField>
              <FormField id="set-tags-out" label="Never documents tagged" hint="Wins over Only documents tagged.">
                <Controller control={control} name="search.tagsExclude" render={({ field }) => <TagInput id="set-tags-out" value={field.value} onChange={field.onChange} placeholder="No tag" />} />
              </FormField>
            </div>
            <SwitchField control={control} name="search.includeUntagged" id="set-untagged" label="Include untagged documents" description="Documents with no tag are searched along with the tagged ones." />
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="set-cond-key" label="Metadata condition" hint={kb.metadataKeys.length ? undefined : 'No metadata field is mapped on this base’s sources yet.'}>
                <Controller control={control} name="search.conditionKey" render={({ field }) => (
                  <Select value={field.value || 'none'} onValueChange={(k) => field.onChange(k === 'none' ? '' : k)} disabled={!kb.metadataKeys.length && !field.value}>
                    <SelectTrigger id="set-cond-key" className="w-60 bg-background"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">No condition</SelectItem>
                      {Array.from(new Set([...kb.metadataKeys, ...(field.value ? [field.value] : [])])).map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}
                    </SelectContent>
                  </Select>
                )} />
              </FormField>
              {!!v.search.conditionKey && (
                <FormField id="set-cond-value" label="equals" hint="Exact match on a metadata field this base’s sources map. All conditions must hold." error={err('search.conditionValue')?.message}>
                  <Controller control={control} name="search.conditionValue" render={({ field }) => <Input id="set-cond-value" className="bg-background" {...field} aria-invalid={!!err('search.conditionValue')} />} />
                </FormField>
              )}
            </div>
            <SwitchField control={control} name="search.rerank" id="set-rerank" label="Rerank" description="A model scores the best 20 pieces from 0 to 10 for how well they answer the question, and the pieces returned follow its order." />
            <SwitchField control={control} name="search.rewrite" id="set-rewrite" label="Rewrite the question" description="A model rewrites the question with your instruction before it is searched. The Playground shows the question as asked and as searched." />
            {v.search.rewrite && (
              <FormField id="set-instruction" label="Rewrite instruction" hint="For example: name the product the customer asks about, and use the bank’s terms for it." error={err('search.rewriteInstructions')?.message}>
                <Controller control={control} name="search.rewriteInstructions" render={({ field }) => <Textarea id="set-instruction" rows={3} {...field} />} />
              </FormField>
            )}
            {(v.search.rerank || v.search.rewrite) && (
              <FormField id="set-query-model" label="Model alias" hint="The models-service chat alias both steps call. Empty uses the installation’s default.">
                <Controller control={control} name="search.queryModel" render={({ field }) => <Input id="set-query-model" className="w-60 bg-background font-mono text-sm" placeholder="Installation default" {...field} />} />
              </FormField>
            )}
          </div>
        </SettingsSection>

        <SettingsSection title="Answer" description="What a search of this base gives back. The agent’s own model, temperature and instructions write the words.">
          <div className="flex flex-col gap-5">
            <FormField id="set-shape" label="Gives back" hint={v.answer.shape === 'chunks' ? 'Pieces only: no answer is withheld; the agent or workflow answers from the pieces.' : 'An answer that cites the pieces it uses.'}>
              <Controller control={control} name="answer.shape" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="set-shape" className="w-60 bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="answer_with_citations">An answer with citations</SelectItem>
                    <SelectItem value="chunks">Pieces only</SelectItem>
                  </SelectContent>
                </Select>
              )} />
            </FormField>
            {v.answer.shape !== 'chunks' && (
              <SwitchField control={control} name="answer.withholdUncited" id="set-withhold" label="Withhold an answer with no cited piece" description="An answer that cites nothing from this base is replaced by the message below." />
            )}
            <FormField id="set-no-answer" label="When nothing is found" hint="Said when no piece passes the floors, or an answer is withheld." error={err('answer.noAnswerMessage')?.message}>
              <Controller control={control} name="answer.noAnswerMessage" render={({ field }) => <Textarea id="set-no-answer" rows={2} {...field} aria-invalid={!!err('answer.noAnswerMessage')} data-testid="kb-settings-no-answer" />} />
            </FormField>
          </div>
        </SettingsSection>

        <SettingsSection title="Sync" description="How this base takes changes from its sources. Schedules, website crawl and AI steps are per source on the Sources tab.">
          <div className="flex flex-col gap-5">
            <FormField id="set-changes" label="Changes from syncs" hint={v.sync.changes === 'review' ? 'A changed document waits in Changes; the version before it stays searchable until it is approved.' : 'Apply at once puts a changed document in search as soon as it is indexed.'}>
              <Controller control={control} name="sync.changes" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="set-changes" className="w-60 bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="apply">Apply at once</SelectItem>
                    <SelectItem value="review">Wait in Changes for review</SelectItem>
                  </SelectContent>
                </Select>
              )} />
            </FormField>
            <FormField id="set-removed" label="Removed at its source" hint="Keep and flag leaves the last version searchable, marked Removed at source.">
              <Controller control={control} name="sync.removedAtSource" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="set-removed" className="w-60 bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="remove">Remove it from search</SelectItem>
                    <SelectItem value="keep">Keep and flag it</SelectItem>
                  </SelectContent>
                </Select>
              )} />
            </FormField>
            <NumberInput control={control} name="sync.staleAfterDays" id="set-stale" label="Stale after (days)" hint="A document not changed or verified for this long is marked Stale." error={err('sync.staleAfterDays')?.message} />
            <SwitchField control={control} name="sync.notifyOnFailure" id="set-notify" label="Tell the owner when a sync fails" description="An email and a Human Tasks item to the base’s owner after a failing sync." />
          </div>
        </SettingsSection>

        <SettingsSection title="Access" description="Knowledge is shared by the team: everyone in it may search this base, and its builders and admins change it.">
          <div className="flex flex-col gap-5">
            <FormField id="set-owner" label="Owner" hint="Answers for what this base serves; named on every citation’s source." error={err('access.owner')?.message}>
              <Controller control={control} name="access.owner" render={({ field }) => (
                <EntityPicker source={peopleOptions} multiple={false} value={field.value ? [field.value] : []} onChange={(next) => field.onChange(next[0] ?? '')} addLabel="Choose the owner" searchPlaceholder="Search people…" testId="kb-settings-owner" />
              )} />
            </FormField>
            <SwitchField control={control} name="access.mcpEnabled" id="set-mcp" label="Offer as an MCP tool" description="Agents and tools outside Ops AI can search it through the team’s MCP address." />
            <FormField id="set-tool-name" label="Tool name" hint="Lowercase letters, digits and underscores." error={err('access.toolName')?.message}>
              <Controller control={control} name="access.toolName" render={({ field }) => <Input id="set-tool-name" className="bg-background font-mono text-sm" {...field} aria-invalid={!!err('access.toolName')} />} />
            </FormField>
          </div>
        </SettingsSection>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <PageSaveActions dirty={formState.isDirty} saving={update.isPending} invalid={!formState.isValid} onSave={() => void save()} onDiscard={() => reset(saved)} testId="kb-settings-save" />
      </div>
    </form>
  );
}

function SwitchField({ control, name, id, label, description }: { control: Control<Values>; name: FieldPath<Values>; id: string; label: string; description: string }) {
  return (
    <Controller control={control} name={name} render={({ field }) => (
      <SettingsField label={label} description={description} htmlFor={id} className="gap-4">
        <Switch id={id} checked={field.value as boolean} onCheckedChange={field.onChange} data-testid={`kb-settings-${id.replace(/^set-/, '')}`} />
      </SettingsField>
    )} />
  );
}

function NumberInput({ control, name, id, label, hint, error }: { control: Control<Values>; name: FieldPath<Values>; id: string; label: string; hint?: string; error?: string }) {
  return (
    <FormField id={id} label={label} hint={hint} error={error}>
      <Controller control={control} name={name} render={({ field }) => (
        <Input id={id} type="number" className="w-28 bg-background tabular-nums" value={field.value as number} onChange={(e) => field.onChange(e.target.value === '' ? Number.NaN : Number(e.target.value))} onBlur={field.onBlur} aria-invalid={!!error} />
      )} />
    </FormField>
  );
}

function NumberSlider({ control, name, id, label, hint, error }: { control: Control<Values>; name: FieldPath<Values>; id: string; label: string; hint: string; error?: string }) {
  return (
    <FormField id={id} label={label} hint={hint} error={error}>
      <Controller control={control} name={name} render={({ field }) => (
        <div className="flex items-center gap-3">
          <Slider className="max-w-80" value={[field.value as number]} min={0} max={1} step={0.01} onValueChange={([x]) => field.onChange(x)} aria-label={label} />
          <Input id={id} type="number" className="w-24 bg-background text-right tabular-nums" value={field.value as number} min={0} max={1} step={0.01} onChange={(e) => field.onChange(Number(e.target.value))} aria-invalid={!!error} />
        </div>
      )} />
    </FormField>
  );
}
