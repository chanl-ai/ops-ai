'use client';

import * as React from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { SourceValuesForm, valueErrors } from '@/components/sources/source-values-form';
import { useSourcePreview } from '@/hooks/knowledge-queries';
import { count, plural } from '@/lib/format';
import type { SourceKindOption, SourceKindPreview } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

const PREVIEW_DEBOUNCE_MS = 600;
const PREVIEW_ROWS = 50;

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * The live preview of an app source's scope: asked for once the values are valid and have stopped changing for a
 * moment. `enabled` false (another step, or a kind with no preview) asks nothing.
 */
export function useSourceScopePreview(kind: SourceKindOption | null, values: Record<string, unknown>, enabled: boolean) {
  const inputs = kind?.type === 'tool' ? (kind.inputs ?? {}) : {};
  const settled = useDebounced(values, PREVIEW_DEBOUNCE_MS);
  const asking = !!kind?.previews && enabled && Object.keys(valueErrors(inputs, values)).length === 0 && Object.keys(valueErrors(inputs, settled)).length === 0;
  return useSourcePreview({ plugin: kind?.plugin, source: kind?.source, values: settled }, asking);
}

/**
 * What to include from an app's source: its fields, searched pickers for its places, and the live preview when the
 * kind offers one. Shared by Knowledge › Add source and Files › Watch a folder, so both show the same fields.
 */
export function SourceScopeStep({
  idPrefix,
  kind,
  values,
  onChange,
  errors,
  valid,
  preview,
  storedNote,
  onNames,
}: {
  idPrefix: string;
  kind: SourceKindOption;
  values: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  /** The errors to show now (an empty required field only once Next was pressed). */
  errors: Record<string, string>;
  valid: boolean;
  preview: UseQueryResult<SourceKindPreview>;
  storedNote?: string;
  onNames?: (input: string, names: Record<string, string>) => void;
}) {
  const inputs = kind.type === 'tool' ? (kind.inputs ?? {}) : {};
  return (
    <>
      <SourceValuesForm idPrefix={idPrefix} inputs={inputs} values={values} onChange={onChange} errors={errors} onNames={onNames} scopeSource={kind.pickers && kind.plugin && kind.source ? { plugin: kind.plugin, source: kind.source } : undefined} />
      {kind.previews && <PreviewPanel paused={!valid} query={preview} storedNote={storedNote} />}
    </>
  );
}

type PreviewPage = SourceKindPreview['pages'][number];
const PREVIEW_COLUMNS: ColumnDef<PreviewPage>[] = [
  { id: 'page', header: 'Page', cell: ({ row }) => <span className="block max-w-80 truncate font-mono text-xs">{row.original.id}</span> },
  { id: 'outcome', header: 'Outcome', cell: ({ row }) => <span className={cn('text-sm', !row.original.willFetch && 'text-muted-foreground')}>{row.original.outcome}</span> },
];

/** The live preview: each page and its outcome with the counts, or why it is paused, loading or failed. */
export function PreviewPanel({ paused, query, storedNote = 'Nothing is stored until you create the source.' }: { paused: boolean; query: UseQueryResult<SourceKindPreview>; storedNote?: string }) {
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
      <p className="text-xs text-muted-foreground">
        robots.txt is always obeyed. {storedNote}
        {p.pages.length > PREVIEW_ROWS ? ` The first ${PREVIEW_ROWS} pages are listed.` : ''}
      </p>
    </div>
  );
}
