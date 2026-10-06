'use client';

import * as React from 'react';
import { AlertTriangle, Columns2, Loader2, Scissors } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { count, plural } from '@/lib/format';
import type { MetadataMapping, ParsingSettings } from '@/lib/types/knowledge';
import type { IngestPresetId, IngestSettings, SampleDocument, SplitPreview, SplitPreviewInput } from '@/lib/types/knowledge-ingest';
import { cn } from '@/lib/utils';

import { applyPreset, INGEST_PRESETS, strategyMeta } from './ingest-meta';

type Result = { data?: SplitPreview; error?: string; loading: boolean };

function PreviewColumn({ label, result }: { label: string; result: Result }) {
  const p = result.data;
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-md border bg-background" data-testid="split-preview-column">
      <div className="flex flex-col gap-1.5 border-b px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">{label}</span>
          {result.loading && <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Splitting" />}
        </div>
        {p && (
          <>
            <div className="flex flex-wrap gap-1">
              {p.strategies.map((st) => (
                <Badge key={st} variant="secondary" className="font-normal">
                  {strategyMeta(st).label}
                </Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground tabular-nums" data-testid="split-counts">
              <span>
                <span className="font-medium text-foreground">{count(p.counts.chunks)}</span> {p.counts.chunks === 1 ? 'chunk' : 'chunks'}
              </span>
              <span>{plural(p.counts.indexedUnits, 'indexed entry', 'indexed entries')}</span>
              {p.counts.questions > 0 && <span>{plural(p.counts.questions, 'question')}</span>}
              <span>{count(p.counts.tokens)} tokens</span>
              <span>{plural(p.counts.modelCalls, 'model call')}</span>
              {p.counts.removedChars > 0 && <span>{count(p.counts.removedChars)} characters removed</span>}
            </div>
          </>
        )}
      </div>
      {result.error ? (
        <p className="flex items-start gap-2 px-3 pb-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {result.error}
        </p>
      ) : !p ? (
        <div className="flex flex-col gap-2 px-3 pb-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : (
        <div className="flex flex-col gap-2 px-3 pb-3">
          {p.notes.length > 0 && (
            <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
              {p.notes.map((n) => (
                <li key={n}>· {n}</li>
              ))}
            </ul>
          )}
          <ol className="flex max-h-96 flex-col gap-2 overflow-y-auto">
            {p.chunks.map((c) => (
              <li key={c.index} className="rounded-md border bg-muted/30 p-2" data-testid="split-chunk">
                <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="font-mono">#{c.index + 1}</span>
                  <span className="min-w-0 truncate">{c.sectionPath.join(' › ')}</span>
                  <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">
                    {c.kind === 'parent' ? 'parent' : c.kind}
                  </Badge>
                  <span className="ml-auto tabular-nums">{c.tokens} tokens</span>
                </div>
                <p className="text-xs leading-relaxed whitespace-pre-wrap">{c.text}</p>
                {c.questions && c.questions.length > 0 && (
                  <ul className="mt-1.5 flex flex-col gap-0.5 border-l-2 border-primary/40 pl-2 text-xs">
                    {c.questions.map((q) => (
                      <li key={q} className="italic">
                        Q: {q}
                      </li>
                    ))}
                  </ul>
                )}
                {c.children && c.children.length > 0 && (
                  <details className="mt-1.5 text-xs">
                    <summary className="cursor-pointer text-muted-foreground">Indexed as {plural(c.children.length, 'child chunk')}; a match returns this section</summary>
                    <ol className="mt-1 flex flex-col gap-1 pl-3">
                      {c.children.map((ch, i) => (
                        <li key={i} className="list-decimal text-muted-foreground">
                          {ch}
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                {Object.keys(c.metadata).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {Object.entries(c.metadata).map(([k, val]) => (
                      <Badge key={k} variant="outline" className="h-5 font-mono text-[10px] font-normal">
                        {k}={val || '—'}
                      </Badge>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

/**
 * Splits a sample document with the draft settings, and optionally a preset beside it, so the effect of a
 * strategy is visible before saving. Re-runs as settings change.
 */
export function SplitPreviewPanel({
  idPrefix,
  samples,
  samplesLoading,
  ingest,
  parsing,
  mapping,
  onPreview,
}: {
  idPrefix: string;
  samples: SampleDocument[];
  samplesLoading?: boolean;
  ingest: IngestSettings;
  parsing: ParsingSettings;
  mapping: MetadataMapping[];
  onPreview: (input: SplitPreviewInput) => Promise<SplitPreview>;
}) {
  const [sampleId, setSampleId] = React.useState<string>('');
  const [compare, setCompare] = React.useState(false);
  const [presetB, setPresetB] = React.useState<IngestPresetId>('help_centre');
  const [a, setA] = React.useState<Result>({ loading: false });
  const [b, setB] = React.useState<Result>({ loading: false });
  const seq = React.useRef(0);
  const sample = sampleId || samples[0]?.id || '';
  const parse = { ocr: parsing.ocr, tables: parsing.tables, vision: parsing.vision };
  const key = JSON.stringify({ sample, ingest, parse, mapping, compare, presetB });

  // Turning on table rows (the rate table preset) moves the preview to a document that has a table, so the split shows rows.
  const tables = ingest.strategies.includes('table_rows');
  const wasTables = React.useRef(tables);
  React.useEffect(() => {
    if (tables && !wasTables.current && samples.find((x) => x.id === sample)?.format !== 'table') {
      const t = samples.find((x) => x.format === 'table');
      if (t) setSampleId(t.id);
    }
    wasTables.current = tables;
  }, [tables, samples, sample]);

  React.useEffect(() => {
    if (!sample) return;
    const n = ++seq.current;
    const run = async (input: SplitPreviewInput, set: (r: Result) => void) => {
      set({ loading: true });
      try {
        const data = await onPreview(input);
        if (n === seq.current) set({ data, loading: false });
      } catch (e) {
        if (n === seq.current) set({ error: (e as Error).message, loading: false });
      }
    };
    const t = setTimeout(() => {
      void run({ sampleId: sample, ingest, parsing: parse, metadataMapping: mapping }, setA);
      if (compare) void run({ sampleId: sample, ingest: applyPreset(ingest, presetB), parsing: parse, metadataMapping: mapping }, setB);
    }, 250);
    return () => clearTimeout(t);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = samples.find((s) => s.id === sample);
  return (
    <div className="flex flex-col gap-3" data-testid="split-preview">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-56 flex-1 flex-col gap-1.5">
          <Label htmlFor={`${idPrefix}-sample`} className="flex items-center gap-1.5">
            <Scissors className="size-3.5" /> Preview the split on
          </Label>
          <Select value={sample} onValueChange={setSampleId} disabled={samplesLoading || !samples.length}>
            <SelectTrigger id={`${idPrefix}-sample`} className="w-full bg-background" aria-label="Sample document for the split preview">
              <SelectValue placeholder={samplesLoading ? 'Loading sample documents…' : 'Choose a sample document'} />
            </SelectTrigger>
            <SelectContent>
              {samples.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.title} · {s.sourceName}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-1.5">
          <Switch id={`${idPrefix}-compare`} checked={compare} onCheckedChange={setCompare} />
          <Label htmlFor={`${idPrefix}-compare`} className="flex items-center gap-1.5 font-normal">
            <Columns2 className="size-3.5" /> Compare with
          </Label>
          <Select value={presetB} onValueChange={(x) => setPresetB(x as IngestPresetId)} disabled={!compare}>
            <SelectTrigger className="h-8 w-40 bg-background" aria-label="Preset to compare with">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INGEST_PRESETS.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {chosen && (
        <p className="text-xs text-muted-foreground">
          {chosen.format === 'table' ? `Table with columns ${chosen.columns?.join(', ')}.` : `${chosen.format[0].toUpperCase()}${chosen.format.slice(1)} document.`}
          {chosen.version ? ` Version ${chosen.version}, effective ${chosen.effectiveDate}.` : ''} Nothing is saved by previewing.
        </p>
      )}
      <div className={cn('grid gap-3', compare && 'lg:grid-cols-2')}>
        <PreviewColumn label="These settings" result={a} />
        {compare && <PreviewColumn label={`${INGEST_PRESETS.find((p) => p.id === presetB)?.label} preset`} result={b} />}
      </div>
    </div>
  );
}
