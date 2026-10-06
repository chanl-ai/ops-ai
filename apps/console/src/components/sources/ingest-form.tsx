'use client';

import { Info, Plus, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';

import { PARSING_OPTIONS } from '@/components/knowledge/knowledge-meta';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { shortDate } from '@/lib/format';
import type { ParsingSettings } from '@/lib/types/knowledge';
import type { ColumnRole, IngestSettings, IngestStrategy } from '@/lib/types/knowledge-ingest';
import { cn } from '@/lib/utils';

import { applyPreset, INGEST_PRESETS, isAiStrategy, RATE_TABLE_COLUMNS, STRATEGY_META, strategyBlocker } from './ingest-meta';

const ROLE_LABEL: Record<ColumnRole, string> = { searchable: 'Searchable', metadata: 'Metadata (filterable)', ignored: 'Ignored' };

function NumberSlider({ id, label, value, min, max, step, onChange, disabled }: { id: string; label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        <Input id={id} type="number" className="h-7 w-20 bg-background text-right tabular-nums" min={min} max={max} value={value} disabled={disabled} onChange={(e) => onChange(Math.min(max, Math.max(min, Number(e.target.value) || min)))} />
      </div>
      <Slider value={[value]} min={min} max={max} step={step} disabled={disabled} onValueChange={([v]) => onChange(v)} aria-label={label} />
    </div>
  );
}

/**
 * Preset, parsing and ingestion strategies for one source, with the settings each strategy needs. AI steps are
 * labelled with the model they call and that the knowledge owner approves them.
 */
export function IngestForm({
  idPrefix,
  ingest: v,
  parsing,
  onIngest,
  onParsing,
  showApproval,
}: {
  idPrefix: string;
  ingest: IngestSettings;
  parsing: ParsingSettings;
  onIngest: (v: IngestSettings) => void;
  onParsing: (p: ParsingSettings) => void;
  /** Show the saved approval state (source settings); the add dialog has none yet. */
  showApproval?: boolean;
}) {
  const set = (p: Partial<IngestSettings>) => onIngest({ ...v, ...p });
  const toggle = (s: IngestStrategy, on: boolean) => {
    const strategies = on ? [...v.strategies, s] : v.strategies.filter((x) => x !== s);
    const preset = INGEST_PRESETS.find((p) => p.strategies.length === strategies.length && p.strategies.every((x) => strategies.includes(x)))?.id ?? 'custom';
    onIngest({ ...v, strategies, preset, columns: on && s === 'table_rows' && !v.columns.length ? RATE_TABLE_COLUMNS.map((c) => ({ ...c })) : v.columns });
  };
  const has = (s: IngestStrategy) => v.strategies.includes(s);
  const ai = v.strategies.filter(isAiStrategy);
  const splitsText = !has('table_rows') || has('structure') || has('fixed') || has('topic');
  const noSearchable = v.strategies.includes('table_rows') && v.columns.length > 0 && !v.columns.some((c) => c.role === 'searchable');
  const setColumn = (i: number, p: Partial<IngestSettings['columns'][number]>) =>
    set({ columns: v.columns.map((c, j) => (j === i ? { ...c, ...p } : p.key ? { ...c, key: false } : c)) });

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Label>Preset</Label>
        <RadioGroup value={v.preset} onValueChange={(p) => onIngest(applyPreset(v, p as IngestSettings['preset']))} className="grid gap-2 sm:grid-cols-2" aria-label="Ingestion preset">
          {INGEST_PRESETS.map((p) => (
            <label key={p.id} htmlFor={`${idPrefix}-preset-${p.id}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border bg-background p-3', v.preset === p.id && 'border-primary bg-primary/5')}>
              <RadioGroupItem value={p.id} id={`${idPrefix}-preset-${p.id}`} className="mt-0.5" />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{p.label}</span>
                <span className="block text-xs text-muted-foreground">{p.description}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
        {v.preset === 'custom' && <p className="text-xs text-muted-foreground">Custom: the strategies below differ from every preset.</p>}
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        {PARSING_OPTIONS.map((o) => (
          <div key={o.k} className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2">
            <Label htmlFor={`${idPrefix}-p-${o.k}`} className="flex items-center gap-1.5 font-normal">
              {o.label}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="size-3.5 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">{o.tip}</TooltipContent>
              </Tooltip>
            </Label>
            <Switch id={`${idPrefix}-p-${o.k}`} checked={parsing[o.k]} onCheckedChange={(x) => onParsing({ ...parsing, [o.k]: x })} />
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <Label>Strategies</Label>
        <div className="grid gap-2 sm:grid-cols-2">
          {STRATEGY_META.map((s) => {
            const blocked = strategyBlocker(v.strategies, s.value);
            const on = has(s.value);
            return (
              <label
                key={s.value}
                htmlFor={`${idPrefix}-st-${s.value}`}
                className={cn('flex items-start gap-3 rounded-md border bg-background p-3', on && 'border-primary bg-primary/5', blocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer')}
              >
                <Checkbox id={`${idPrefix}-st-${s.value}`} checked={on} disabled={!!blocked} onCheckedChange={(x) => toggle(s.value, !!x)} className="mt-0.5" />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                    {s.label}
                    {s.splitter && (
                      <Badge variant="secondary" className="font-normal">
                        Splits text
                      </Badge>
                    )}
                    {s.ai && (
                      <Badge variant="outline" className="gap-1 font-normal">
                        <Sparkles className="size-3" /> Uses model calls at ingest · {v.model}
                      </Badge>
                    )}
                  </span>
                  <span className="block text-xs text-muted-foreground">{s.description}</span>
                  {s.ai && <span className="mt-1 block text-xs text-amber-700 dark:text-amber-400">Needs the knowledge owner’s approval</span>}
                  {blocked && <span className="mt-1 block text-xs text-muted-foreground">{blocked}</span>}
                </span>
              </label>
            );
          })}
        </div>
      </div>

      {splitsText && (
        <div className="grid gap-6 sm:grid-cols-2">
          <NumberSlider id={`${idPrefix}-size`} label="Chunk size (tokens)" value={v.size} min={100} max={2000} step={16} onChange={(size) => set({ size, overlap: Math.min(v.overlap, size - 10) })} />
          <NumberSlider id={`${idPrefix}-overlap`} label="Overlap (tokens)" value={v.overlap} min={0} max={Math.min(500, v.size - 10)} step={10} onChange={(overlap) => set({ overlap })} />
        </div>
      )}
      {(has('parent_child') || has('faq')) && (
        <div className="grid gap-6 sm:grid-cols-2">
          {has('parent_child') && <NumberSlider id={`${idPrefix}-child`} label="Child chunk size (tokens)" value={v.childSize} min={16} max={512} step={16} onChange={(childSize) => set({ childSize })} />}
          {has('faq') && <NumberSlider id={`${idPrefix}-faq`} label="Questions per section" value={v.questionsPerSection} min={1} max={3} step={1} onChange={(questionsPerSection) => set({ questionsPerSection })} />}
        </div>
      )}

      {has('table_rows') && (
        <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
          <div>
            <Label>Table columns</Label>
            <p className="text-xs text-muted-foreground">Searchable columns are matched by questions and lookups; metadata columns come back as values and can be filtered; ignored columns are dropped. The key column names the row.</p>
          </div>
          {v.columns.map((c, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input className="h-8 min-w-36 flex-1 font-mono text-xs" value={c.name} placeholder="e.g. Product" aria-label="Column name" onChange={(e) => setColumn(i, { name: e.target.value })} />
              <Select value={c.role} onValueChange={(r) => setColumn(i, { role: r as ColumnRole, key: r === 'searchable' ? c.key : false })}>
                <SelectTrigger className="h-8 w-48" aria-label={`Role of ${c.name || 'column'}`} aria-invalid={noSearchable || undefined} aria-describedby={noSearchable ? `${idPrefix}-columns-error` : undefined}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(ROLE_LABEL) as ColumnRole[]).map((r) => (
                    <SelectItem key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <label htmlFor={`${idPrefix}-key-${i}`} className={cn('flex items-center gap-1.5 text-xs', c.role !== 'searchable' && 'opacity-50')}>
                <Checkbox id={`${idPrefix}-key-${i}`} checked={!!c.key} disabled={c.role !== 'searchable'} onCheckedChange={(x) => setColumn(i, { key: !!x })} /> Key
              </label>
              <Button variant="ghost" size="icon" className="size-8" onClick={() => set({ columns: v.columns.filter((_, j) => j !== i) })} aria-label={`Remove ${c.name || 'column'}`}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          {noSearchable && (
            <p role="alert" id={`${idPrefix}-columns-error`} data-field-error className="text-xs text-destructive">
              Mark at least one column as searchable, so questions and lookups can match a row.
            </p>
          )}
          <Button variant="outline" size="sm" className="w-fit" onClick={() => set({ columns: [...v.columns, { name: '', role: 'searchable' }] })}>
            <Plus className="size-3.5" /> Add column
          </Button>
        </div>
      )}

      {ai.length > 0 && (
        <Alert>
          <ShieldCheck className="size-4" />
          <AlertTitle>
            {showApproval && v.approval.status === 'approved' && ai.every((s) => v.approval.approvedSteps.includes(s))
              ? `AI steps approved${v.approval.decidedBy ? ` by ${v.approval.decidedBy}` : ''}${v.approval.decidedAt ? ` on ${shortDate(v.approval.decidedAt)}` : ''}`
              : 'AI steps need the knowledge owner’s approval'}
          </AlertTitle>
          <AlertDescription>
            {ai.map((s) => STRATEGY_META.find((m) => m.value === s)!.label).join(' and ')} call {v.model} once per section at ingest. Until the knowledge owner approves them, syncs and re-indexes run without them; the preview below always shows their effect.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
