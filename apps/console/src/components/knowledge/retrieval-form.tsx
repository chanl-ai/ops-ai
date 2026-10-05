'use client';

import { Info, Plus, Trash2 } from 'lucide-react';

import { Section } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
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
import type { MetadataFilter, RetrievalSettings, Source } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

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

function FiltersEditor({ value, onChange, keys, disabled }: { value: MetadataFilter[]; onChange: (v: MetadataFilter[]) => void; keys: string[]; disabled?: boolean }) {
  const patch = (i: number, p: Partial<MetadataFilter>) => onChange(value.map((x, j) => (j === i ? { ...x, ...p } : x)));
  return (
    <div className="flex flex-col gap-2">
      {value.map((f, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <Input list="rf-keys" className="h-8 w-32 font-mono text-xs" value={f.key} placeholder="e.g. locale" aria-label="Metadata key" onChange={(e) => patch(i, { key: e.target.value })} disabled={disabled} />
          <Select value={f.op} onValueChange={(op) => patch(i, { op: op as MetadataFilter['op'] })} disabled={disabled}>
            <SelectTrigger className="h-8 w-24" aria-label="Operator">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="equals">equals</SelectItem>
              <SelectItem value="in">in</SelectItem>
              <SelectItem value="not">not</SelectItem>
            </SelectContent>
          </Select>
          <Input className="h-8 min-w-24 flex-1 font-mono text-xs" value={f.value} placeholder={f.op === 'in' ? 'e.g. 2025, 2026' : 'e.g. en'} aria-label="Value" onChange={(e) => patch(i, { value: e.target.value })} disabled={disabled} />
          {!disabled && (
            <Button variant="ghost" size="icon" className="size-8" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="Remove filter">
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      ))}
      <datalist id="rf-keys">
        {keys.map((k) => (
          <option key={k} value={k} />
        ))}
      </datalist>
      {!disabled && (
        <Button variant="outline" size="sm" className="h-7 w-fit" onClick={() => onChange([...value, { key: '', op: 'equals', value: '' }])}>
          <Plus className="size-3.5" /> Add filter
        </Button>
      )}
    </div>
  );
}

/** One form, two variants: the full Retrieval tab and the playground's compact settings rail. */
export function RetrievalForm({
  value: v,
  onChange,
  sources,
  metadataKeys,
  models,
  variant,
  disabled,
}: {
  value: RetrievalSettings;
  onChange: (patch: Partial<RetrievalSettings>) => void;
  sources: Pick<Source, 'id' | 'name'>[];
  metadataKeys: string[];
  models: string[];
  variant: 'full' | 'rail';
  disabled?: boolean;
}) {
  const rail = variant === 'rail';
  const search = (
    <div className={cn('flex flex-col', rail ? 'gap-4' : 'gap-5')}>
      <div className="flex flex-col gap-2">
        <Label className="flex items-center gap-1.5">
          Search mode <Tip text="Hybrid fuses semantic and keyword results with reciprocal rank fusion." />
        </Label>
        <RadioGroup value={v.searchMode} onValueChange={(x) => onChange({ searchMode: x as RetrievalSettings['searchMode'] })} className="flex flex-wrap gap-2" disabled={disabled}>
          {(['semantic', 'keyword', 'hybrid'] as const).map((m) => (
            <label key={m} htmlFor={`sm-${variant}-${m}`} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm capitalize', v.searchMode === m && 'border-primary bg-primary/5')}>
              <RadioGroupItem value={m} id={`sm-${variant}-${m}`} /> {m}
            </label>
          ))}
        </RadioGroup>
      </div>
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor={`rerank-${variant}`} className="flex items-center gap-1.5">
          Rerank <Tip text="Reranks the top 50 hits with a cross-encoder before applying the chunk limit." />
        </Label>
        <div className="flex items-center gap-2">
          {v.rerank && !rail && (
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
          <Switch id={`rerank-${variant}`} checked={v.rerank} onCheckedChange={(x) => onChange({ rerank: x })} disabled={disabled} />
        </div>
      </div>
      <SliderField id={`limit-${variant}`} label="Chunk limit" tip="Chunks returned per query." value={v.chunkLimit} min={1} max={20} step={1} onChange={(x) => onChange({ chunkLimit: x })} disabled={disabled} note={v.chunkLimit > 12 && !v.rerank ? 'Above 12 without rerank tends to dilute answers.' : undefined} />
      <SliderField id={`threshold-${variant}`} label="Relevance threshold" tip="Hits below are dropped; if none remain the response is a no-answer." value={v.threshold} min={0} max={1} step={0.05} onChange={(x) => onChange({ threshold: Math.round(x * 100) / 100 })} disabled={disabled} />
      {!rail && (
        <>
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="rewrite" className="flex items-center gap-1.5">
                Query rewriting <Tip text="The model reformulates the question before searching." />
              </Label>
              <Switch id="rewrite" checked={v.queryRewrite} onCheckedChange={(x) => onChange({ queryRewrite: x })} disabled={disabled} />
            </div>
            {v.queryRewrite && (
              <Textarea value={v.rewriteInstructions} onChange={(e) => onChange({ rewriteInstructions: e.target.value })} placeholder="e.g. Expand abbreviations; add the product name when it is implied." rows={2} maxLength={1000} disabled={disabled} aria-label="Rewrite instructions" />
            )}
          </div>
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
        </>
      )}
    </div>
  );

  const synthesis = (
    <div className={cn('flex flex-col', rail ? 'gap-4' : 'gap-5')}>
      <div className="flex items-center justify-between">
        <Label htmlFor={`synth-${variant}`} className="flex items-center gap-1.5">
          Synthesise answer <Tip text="Off returns chunks only, for the agent to answer from." />
        </Label>
        <Switch id={`synth-${variant}`} checked={v.synthesis} onCheckedChange={(x) => onChange({ synthesis: x })} disabled={disabled} />
      </div>
      {v.synthesis && (
        <>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`model-${variant}`}>Model</Label>
            <Select value={v.model} onValueChange={(x) => onChange({ model: x })} disabled={disabled}>
              <SelectTrigger id={`model-${variant}`} className="w-full">
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
          <SliderField id={`temp-${variant}`} label="Temperature" value={v.temperature} min={0} max={1} step={0.1} onChange={(x) => onChange({ temperature: Math.round(x * 10) / 10 })} disabled={disabled} />
          {!rail && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="max-tokens">Max answer tokens</Label>
              <Input id="max-tokens" type="number" min={64} max={4096} value={v.maxTokens} onChange={(e) => onChange({ maxTokens: Number(e.target.value) })} className="w-32" disabled={disabled} />
            </div>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor={`instr-${variant}`}>System instructions</Label>
            <Textarea id={`instr-${variant}`} value={v.instructions} onChange={(e) => onChange({ instructions: e.target.value })} rows={rail ? 3 : 4} maxLength={4000} disabled={disabled} />
            <p className="text-xs text-muted-foreground">{v.instructions.length} / 4000</p>
          </div>
          {!rail && (
            <>
              <div className="flex flex-col gap-2">
                <Label>Citation style</Label>
                <RadioGroup value={v.citationStyle} onValueChange={(x) => onChange({ citationStyle: x as RetrievalSettings['citationStyle'] })} className="flex flex-wrap gap-2" disabled={disabled}>
                  {(
                    [
                      ['inline', 'Inline markers [1]'],
                      ['footnotes', 'Footnotes'],
                      ['links', 'Source links only'],
                      ['none', 'None'],
                    ] as const
                  ).map(([k, l]) => (
                    <label key={k} htmlFor={`cs-${k}`} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm', v.citationStyle === k && 'border-primary bg-primary/5')}>
                      <RadioGroupItem value={k} id={`cs-${k}`} /> {l}
                    </label>
                  ))}
                </RadioGroup>
                <p className="text-xs text-muted-foreground">Citations carry section, page and version, and the answer names the document it followed when precedence applied.</p>
              </div>
              <div className="flex items-center justify-between">
                <Label htmlFor="tables" className="flex items-center gap-1.5">
                  Return tables as structured values <Tip text="Fee schedules, limits and eligibility bands come back as values, not paragraphs." />
                </Label>
                <Switch id="tables" checked={v.structuredTables} onCheckedChange={(x) => onChange({ structuredTables: x })} disabled={disabled} />
              </div>
              <div className="flex items-center justify-between">
                <Label htmlFor="include-chunks" className="flex items-center gap-1.5">
                  Include source chunks in the response <Tip text="Affects API and MCP payload size." />
                </Label>
                <Switch id="include-chunks" checked={v.includeChunks} onCheckedChange={(x) => onChange({ includeChunks: x })} disabled={disabled} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="no-answer">No-answer message</Label>
                <Input id="no-answer" value={v.noAnswerMessage} onChange={(e) => onChange({ noAnswerMessage: e.target.value })} disabled={disabled} />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );

  const defaults = (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label className="flex items-center gap-1.5">
          Default metadata filters <Tip text="Applied to every query unless the caller sends its own filters." />
        </Label>
        <FiltersEditor value={v.defaultFilters} onChange={(x) => onChange({ defaultFilters: x })} keys={metadataKeys} disabled={disabled} />
      </div>
      <div className={cn('grid gap-3', !rail && 'sm:grid-cols-2')}>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`tags-in-${variant}`}>Tags include</Label>
          <TagInput id={`tags-in-${variant}`} value={v.tagsInclude} onChange={(x) => onChange({ tagsInclude: x })} placeholder="e.g. policy" disabled={disabled} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`tags-out-${variant}`}>Tags exclude</Label>
          <TagInput id={`tags-out-${variant}`} value={v.tagsExclude} onChange={(x) => onChange({ tagsExclude: x })} placeholder="e.g. draft" disabled={disabled} />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <Label htmlFor={`untagged-${variant}`}>Include untagged documents</Label>
        <Switch id={`untagged-${variant}`} checked={v.includeUntagged} onCheckedChange={(x) => onChange({ includeUntagged: x })} disabled={disabled} />
      </div>
    </div>
  );

  if (rail) {
    const n = v.defaultFilters.length + v.tagsInclude.length + v.tagsExclude.length;
    return (
      <div className="flex flex-col gap-5">
        {search}
        <div className="border-t pt-4">{synthesis}</div>
        <Accordion type="multiple" className="border-t">
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
            <AccordionContent>{defaults}</AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Section title="Search" description="How a question becomes chunks">
        {search}
      </Section>
      <Section title="Answer synthesis" description="Whether and how the chunks become an answer">
        {synthesis}
      </Section>
      <Section title="Defaults" description="Applied to every query from agents, the API and MCP">
        {defaults}
      </Section>
    </div>
  );
}
