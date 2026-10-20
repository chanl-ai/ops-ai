'use client';

import { Info } from 'lucide-react';

import { Section } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { RetrievalSettings, Source } from '@/lib/types/knowledge';
import type { AnswerShape, QueryMode, RewriteMode } from '@/lib/types/knowledge-retrieval';
import { cn } from '@/lib/utils';

import { FilterBuilder } from './filter-builder';
import { ANSWER_SHAPES, QUERY_MODES, REWRITE_LABEL } from './retrieval-meta';

function Tip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Info className="size-3.5 text-muted-foreground" />
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{text}</TooltipContent>
    </Tooltip>
  );
}

function SliderField({ id, label, tip, value, min, max, step, onChange, disabled, note }: { id: string; label: string; tip?: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; disabled?: boolean; note?: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <Label htmlFor={id} className="flex items-center gap-1.5">
          {label}
          {tip && <Tip text={tip} />}
        </Label>
        <Input id={id} type="number" className="h-7 w-20 text-right tabular-nums" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} disabled={disabled} />
      </div>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={([x]) => onChange(x)} disabled={disabled} aria-label={label} />
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

/** One form, two variants: the knowledge base's saved defaults (Retrieval tab) and per-call overrides (playground rail). */
export function RetrievalForm({
  value: v,
  onChange,
  sources,
  metadataKeys,
  models,
  variant,
  idPrefix = variant,
  disabled,
}: {
  value: RetrievalSettings;
  onChange: (patch: Partial<RetrievalSettings>) => void;
  sources: Pick<Source, 'id' | 'name'>[];
  metadataKeys: string[];
  models: string[];
  variant: 'full' | 'rail';
  /** Distinguishes two forms on one page (playground compare). */
  idPrefix?: string;
  disabled?: boolean;
}) {
  const rail = variant === 'rail';
  const id = (x: string) => `${idPrefix}-${x}`;
  const table = v.searchMode === 'table_lookup';

  const search = (
    <div className={cn('flex flex-col', rail ? 'gap-4' : 'gap-5')}>
      <div className="flex flex-col gap-2">
        <Label className="flex items-center gap-1.5">Query mode</Label>
        <RadioGroup value={v.searchMode} onValueChange={(x) => onChange({ searchMode: x as QueryMode })} className={cn('grid gap-2', !rail && 'sm:grid-cols-2 lg:grid-cols-3')} disabled={disabled} aria-label="Query mode">
          {QUERY_MODES.map((m) => (
            <label key={m.value} htmlFor={id(`mode-${m.value}`)} className={cn('flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-1.5', v.searchMode === m.value && 'border-primary bg-primary/5')}>
              <RadioGroupItem value={m.value} id={id(`mode-${m.value}`)} className="mt-0.5" />
              <span className="min-w-0">
                <span className="block text-sm">{m.label}</span>
                {!rail && <span className="block text-xs text-muted-foreground">{m.description}</span>}
              </span>
            </label>
          ))}
        </RadioGroup>
      </div>
      {v.searchMode === 'hybrid' && (
        <SliderField
          id={id('weight')}
          label="Semantic weight"
          tip="0 is keyword only, 1 is semantic only."
          value={v.hybridWeight}
          min={0}
          max={1}
          step={0.05}
          onChange={(x) => onChange({ hybridWeight: Math.round(x * 100) / 100 })}
          disabled={disabled}
          note={`Semantic ${Math.round(v.hybridWeight * 100)}% · keyword ${Math.round((1 - v.hybridWeight) * 100)}%`}
        />
      )}
      {v.searchMode === 'as_of' && (
        <div className="flex flex-col gap-2">
          <Label htmlFor={id('asof')}>In force on</Label>
          <Input id={id('asof')} type="date" className="w-44" value={v.asOf} onChange={(e) => onChange({ asOf: e.target.value })} disabled={disabled} />
          <p className="text-xs text-muted-foreground">{v.asOf ? 'Each document is read in the version that was in force that day.' : 'Empty means today.'}</p>
        </div>
      )}
      {table && <p className="text-xs text-muted-foreground">Searches only sources that ingest table rows, and matches amounts against row bands.</p>}
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor={id('rerank')} className="flex items-center gap-1.5">
          Rerank <Tip text="Reads the top 30 passages more closely and reorders them before the threshold and chunk limit." />
        </Label>
        <div className="flex items-center gap-2">
          {v.rerank && !rail && !table && (
            <Select value={v.reranker} onValueChange={(x) => onChange({ reranker: x as RetrievalSettings['reranker'] })} disabled={disabled}>
              <SelectTrigger className="h-8 w-40" aria-label="Reranker">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="hosted">Hosted default</SelectItem>
                <SelectItem value="cross-encoder">Cross-encoder</SelectItem>
              </SelectContent>
            </Select>
          )}
          <Switch id={id('rerank')} checked={v.rerank && !table} onCheckedChange={(x) => onChange({ rerank: x })} disabled={disabled || table} />
        </div>
      </div>
      <SliderField id={id('limit')} label="Chunk limit" tip="Passages returned per query." value={v.chunkLimit} min={1} max={20} step={1} onChange={(x) => onChange({ chunkLimit: x })} disabled={disabled} note={v.chunkLimit > 12 && !v.rerank ? 'Above 12 without rerank tends to dilute answers.' : undefined} />
      <SliderField id={id('threshold')} label="Relevance threshold" tip="Passages below are dropped; if none remain the response is a no-answer." value={v.threshold} min={0} max={1} step={0.05} onChange={(x) => onChange({ threshold: Math.round(x * 100) / 100 })} disabled={disabled} />
      <div className="flex flex-col gap-2">
        <Label htmlFor={id('rewrite')} className="flex items-center gap-1.5">
          Query rewriting <Tip text="Rewrite tidies the question into document language; expand searches several phrasings and keeps each passage’s best score." />
        </Label>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={v.rewrite} onValueChange={(x) => onChange({ rewrite: x as RewriteMode })} disabled={disabled}>
            <SelectTrigger id={id('rewrite')} className="h-8 w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(REWRITE_LABEL) as RewriteMode[]).map((k) => (
                <SelectItem key={k} value={k}>
                  {REWRITE_LABEL[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {v.rewrite === 'expand' && (
            <Select value={String(v.expandCount)} onValueChange={(x) => onChange({ expandCount: Number(x) })} disabled={disabled}>
              <SelectTrigger className="h-8 w-32" aria-label="Phrasings">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[2, 3, 4].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n} phrasings
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        {v.rewrite !== 'off' && !rail && (
          <Textarea value={v.rewriteInstructions} onChange={(e) => onChange({ rewriteInstructions: e.target.value })} placeholder="e.g. Expand abbreviations; add the product name when it is implied." rows={2} maxLength={1000} disabled={disabled} aria-label="Rewrite instructions" />
        )}
      </div>
      {!rail && (
        <div className="flex flex-col gap-2">
          <Label>Search scope</Label>
          <div className="flex flex-wrap gap-1.5">
            {sources.map((s) => {
              const on = v.scopeSourceIds.length === 0 || v.scopeSourceIds.includes(s.id);
              return (
                <button
                  key={s.id}
                  type="button"
                  disabled={disabled}
                  aria-pressed={on}
                  onClick={() => {
                    const all = sources.map((x) => x.id);
                    const cur = v.scopeSourceIds.length ? v.scopeSourceIds : all;
                    const next = on ? cur.filter((x) => x !== s.id) : [...cur, s.id];
                    onChange({ scopeSourceIds: next.length === all.length ? [] : next });
                  }}
                  className={cn('rounded-full border px-2.5 py-1 text-xs', on ? 'border-primary bg-primary/5' : 'text-muted-foreground')}
                >
                  {s.name}
                </button>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">{v.scopeSourceIds.length === 0 ? 'All attached sources' : `${v.scopeSourceIds.length} of ${sources.length} sources`}</p>
        </div>
      )}
    </div>
  );

  const synthesis = (
    <div className={cn('flex flex-col', rail ? 'gap-4' : 'gap-5')}>
      <div className="flex flex-col gap-2">
        <Label>Answer shape</Label>
        <RadioGroup value={v.answerShape} onValueChange={(x) => onChange({ answerShape: x as AnswerShape })} className="grid gap-2" disabled={disabled} aria-label="Answer shape">
          {ANSWER_SHAPES.map((m) => (
            <label key={m.value} htmlFor={id(`shape-${m.value}`)} className={cn('flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-1.5', v.answerShape === m.value && 'border-primary bg-primary/5')}>
              <RadioGroupItem value={m.value} id={id(`shape-${m.value}`)} className="mt-0.5" />
              <span className="min-w-0">
                <span className="block text-sm">{m.label}</span>
                {!rail && <span className="block text-xs text-muted-foreground">{m.description}</span>}
              </span>
            </label>
          ))}
        </RadioGroup>
      </div>
      {v.answerShape !== 'chunks' && (
        <>
          <div className="flex flex-col gap-2">
            <Label htmlFor={id('model')}>Model</Label>
            <Select value={v.model} onValueChange={(x) => onChange({ model: x })} disabled={disabled}>
              <SelectTrigger id={id('model')} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Array.from(new Set([...models, v.model])).map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <SliderField id={id('temp')} label="Temperature" value={v.temperature} min={0} max={1} step={0.1} onChange={(x) => onChange({ temperature: Math.round(x * 10) / 10 })} disabled={disabled} />
          {!rail && (
            <div className="flex flex-col gap-2">
              <Label htmlFor={id('max-tokens')}>Max answer tokens</Label>
              <Input id={id('max-tokens')} type="number" min={64} max={4096} value={v.maxTokens} onChange={(e) => onChange({ maxTokens: Number(e.target.value) })} className="w-32" disabled={disabled} />
            </div>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor={id('instr')}>Instruction</Label>
            <Textarea id={id('instr')} value={v.instructions} onChange={(e) => onChange({ instructions: e.target.value })} rows={rail ? 3 : 4} maxLength={4000} disabled={disabled} />
            <p className="text-xs text-muted-foreground">{v.instructions.length} / 4000</p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={id('cite')}>Citation style</Label>
            <Select value={v.citationStyle} onValueChange={(x) => onChange({ citationStyle: x as RetrievalSettings['citationStyle'] })} disabled={disabled}>
              <SelectTrigger id={id('cite')} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inline">Inline markers [1]</SelectItem>
                <SelectItem value="footnotes">Footnotes</SelectItem>
                <SelectItem value="links">Source links only</SelectItem>
                <SelectItem value="none">None</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {!rail && (
            <>
              <div className="flex items-center justify-between">
                <Label htmlFor={id('tables')} className="flex items-center gap-1.5">
                  Return tables as structured values <Tip text="Fee schedules, limits and eligibility bands come back as values, not paragraphs." />
                </Label>
                <Switch id={id('tables')} checked={v.structuredTables} onCheckedChange={(x) => onChange({ structuredTables: x })} disabled={disabled} />
              </div>
              <div className="flex items-center justify-between">
                <Label htmlFor={id('include-chunks')} className="flex items-center gap-1.5">
                  Include source chunks in the response <Tip text="Affects API and MCP payload size." />
                </Label>
                <Switch id={id('include-chunks')} checked={v.includeChunks} onCheckedChange={(x) => onChange({ includeChunks: x })} disabled={disabled} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor={id('no-answer')}>No-answer message</Label>
                <Input id={id('no-answer')} value={v.noAnswerMessage} onChange={(e) => onChange({ noAnswerMessage: e.target.value })} disabled={disabled} />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );

  const filters = (
    <div className="flex flex-col gap-4">
      <FilterBuilder idPrefix={id('flt')} value={v.filters} onChange={(x) => onChange({ filters: x })} keys={metadataKeys} disabled={disabled} />
      <div className={cn('grid gap-3', !rail && 'sm:grid-cols-2')}>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={id('tags-in')}>Tags include</Label>
          <TagInput id={id('tags-in')} value={v.tagsInclude} onChange={(x) => onChange({ tagsInclude: x })} placeholder="e.g. policy" disabled={disabled} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={id('tags-out')}>Tags exclude</Label>
          <TagInput id={id('tags-out')} value={v.tagsExclude} onChange={(x) => onChange({ tagsExclude: x })} placeholder="e.g. draft" disabled={disabled} />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <Label htmlFor={id('untagged')}>Include untagged documents</Label>
        <Switch id={id('untagged')} checked={v.includeUntagged} onCheckedChange={(x) => onChange({ includeUntagged: x })} disabled={disabled} />
      </div>
    </div>
  );

  if (rail) {
    const n = v.filters.conditions.length + v.tagsInclude.length + v.tagsExclude.length;
    return (
      <div className="flex flex-col gap-5">
        {search}
        <Accordion type="multiple" defaultValue={n ? ['filters'] : []} className="border-t">
          <AccordionItem value="filters">
            <AccordionTrigger className="text-sm">
              <span>
                Filters and tags
                {n > 0 && (
                  <Badge variant="secondary" className="ml-2 font-normal">
                    {n}
                  </Badge>
                )}
              </span>
            </AccordionTrigger>
            <AccordionContent>{filters}</AccordionContent>
          </AccordionItem>
          <AccordionItem value="answer">
            <AccordionTrigger className="text-sm">Answer</AccordionTrigger>
            <AccordionContent>{synthesis}</AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Section title="Search" description="How a question becomes passages">
        {search}
      </Section>
      <Section title="Filters" description="Applied before ranking to every query from agents, workflows, the API and MCP, unless the call overrides them">
        {filters}
      </Section>
      <Section title="Answer" description="Whether and how the passages become an answer">
        {synthesis}
      </Section>
    </div>
  );
}
