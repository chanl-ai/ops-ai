'use client';

import * as React from 'react';
import { FileSearch, Pencil } from 'lucide-react';
import { toast } from 'sonner';

import { correctedRecords, DocumentReadSection, hasCorrections, type ReadEdits } from '@/components/reviews/document-read';
import { EmptyState } from '@/components/shared/empty-state';
import { FieldRow } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { ConfidenceBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useCorrectFields } from '@/hooks/extraction-queries';
import { plural } from '@/lib/format';
import type { DocumentRead } from '@/lib/types/domain';
import type { Extraction } from '@/lib/types/extractions';
import { cn } from '@/lib/utils';

/**
 * An extraction as the read check draws it, so a file's fields look the same here and in Human Tasks. Read-only, a
 * corrected field shows the person's value with what was read beside it; while editing, the inputs start from the
 * current values.
 */
export function asDocumentRead(row: Extraction, fileName: string, editing = false): DocumentRead {
  const rows = row.records ?? (row.fields ? [{ values: Object.fromEntries(Object.entries(row.fields).map(([k, f]) => [k, f.value])), fields: row.fields }] : []);
  const anyCorrected = rows.some((r) => Object.values(r.fields).some((f) => f.corrected));
  const asRead = (r: (typeof rows)[number]) => ({ ...r, values: Object.fromEntries(Object.entries(r.values).map(([k, v]) => [k, r.fields[k]?.corrected ? r.fields[k].extractedValue : v])) });
  return {
    fileId: row.fileId,
    fileName,
    floor: row.floor ?? null,
    schema: row.schema ?? [],
    records: editing || !anyCorrected ? rows : rows.map(asRead),
    editable: editing,
    corrected: editing || !anyCorrected ? null : rows.map((r) => r.values),
  };
}

/**
 * The newest read's fields, or what to do when there is none. With `canEdit`, Edit fields turns the values into inputs
 * and Save sends each changed field as a correction; the value as read stays beside it.
 */
/** A read that found no fields: Detect matched none of the team's types. Says so, and offers to read it with a type. */
function NoFieldsRead({ onExtract, canExtract }: { onExtract: () => void; canExtract: boolean }) {
  return (
    <EmptyState
      icon={FileSearch}
      title="No fields were read"
      description="This file matched none of the team's document types. Extract again and choose its type."
      action={canExtract ? { label: 'Extract', onClick: onExtract } : undefined}
      testId="file-no-fields"
    />
  );
}

export function FileFields({ latest, fileName, onExtract, canExtract, canEdit = false }: { latest: Extraction | null; fileName: string; onExtract: () => void; canExtract: boolean; canEdit?: boolean }) {
  const [editing, setEditing] = React.useState(false);
  const [edits, setEdits] = React.useState<ReadEdits>({});
  const save = useCorrectFields(latest?.fileId ?? '');
  if (!latest)
    return (
      <EmptyState
        icon={FileSearch}
        title="Not read yet"
        description="Extract reads the file with a document type and lists each field with its confidence and the text it came from."
        action={canExtract ? { label: 'Extract', onClick: onExtract } : undefined}
      />
    );
  if (latest.status === 'unreadable') return <EmptyState icon={FileSearch} title="No text could be read" description="The file has no text layer the reader could use. Scanned pages need OCR, which arrives with page images." />;
  if (latest.status === 'done' && !latest.schema?.length) return <NoFieldsRead onExtract={onExtract} canExtract={canExtract} />;
  const read = asDocumentRead(latest, fileName, editing);
  const changed = editing && hasCorrections(read, edits);
  const submit = async () => {
    const next = correctedRecords(read, edits);
    const many = !!latest.records;
    const changes = next.flatMap((r, i) => Object.keys(edits[i] ?? {}).filter((k) => r.values[k] !== read.records[i].values[k]).map((key) => ({ key, value: r.values[key], record: many ? i : undefined })));
    try {
      await save.mutateAsync({ id: latest.id, changes });
      toast.success(changes.length === 1 ? 'Saved the correction' : `Saved ${changes.length} corrections`, { position: 'top-center', description: 'The value as read stays beside each one.' });
      setEdits({});
      setEditing(false);
    } catch (e) {
      toast.error('Couldn’t save the corrections', { description: (e as Error).message });
    }
  };
  return (
    <div className="flex flex-col gap-3">
      {canEdit && latest.status === 'done' && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {editing ? (
            <>
              <Button variant="outline" size="sm" onClick={() => (setEdits({}), setEditing(false))} disabled={save.isPending}>
                Cancel
              </Button>
              <LoadingButton size="sm" onClick={submit} isLoading={save.isPending} loadingText="Saving…" disabled={!changed} data-testid="fields-save">
                Save corrections
              </LoadingButton>
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setEditing(true)} data-testid="fields-edit">
              <Pencil className="size-4" /> Edit fields
            </Button>
          )}
        </div>
      )}
      <DocumentReadSection read={read} open={editing} edits={edits} onEdit={(record, key, text) => setEdits((x) => ({ ...x, [record]: { ...(x[record] ?? {}), [key]: text } }))} />
    </div>
  );
}

/**
 * The newest read beside the page (Preview): one line per field with its value and confidence, the quote under it in
 * full on hover. Fields to check come first, as in the read check.
 */
export function FileFieldList({ latest, onExtract, canExtract, selected, onSelect }: { latest: Extraction | null; onExtract: () => void; canExtract: boolean; selected?: string | null; onSelect?: (key: string) => void }) {
  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (selected) listRef.current?.querySelector(`[data-testid="side-field-${CSS.escape(selected)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selected]);
  if (!latest || latest.status !== 'done') return <FileFields latest={latest} fileName="" onExtract={onExtract} canExtract={canExtract} />;
  if (!latest.schema?.length) return <NoFieldsRead onExtract={onExtract} canExtract={canExtract} />;
  const record = latest.records?.[0] ?? (latest.fields ? { values: {}, fields: latest.fields } : null);
  if (!record) return null;
  // A person's correction settles a field, whatever the read thought of it.
  const toCheck = (k: string) => !!record.fields[k]?.needsReview && !record.fields[k]?.corrected;
  const schema = [...(latest.schema ?? [])].sort((a, b) => Number(toCheck(b.key)) - Number(toCheck(a.key)));
  const check = schema.filter((f) => toCheck(f.key)).length;
  return (
    <div ref={listRef} className="flex min-w-0 flex-col gap-2" data-testid="file-field-list">
      <p className="text-xs text-muted-foreground">
        {plural(schema.length, 'field')}
        {check ? ` · ${plural(check, 'field')} to check` : ''}
        {latest.records && latest.records.length > 1 ? ` · first of ${latest.records.length} records` : ''}
      </p>
      <div className="rounded-lg border px-3">
        {schema.map((f) => {
          const scored = record.fields[f.key];
          const value = scored?.value;
          const empty = value === null || value === undefined || value === '';
          const quote = scored?.citation?.quote;
          return (
            <div
              key={f.key}
              role="button"
              tabIndex={0}
              aria-pressed={selected === f.key}
              onClick={() => onSelect?.(f.key)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect?.(f.key))}
              className={cn('-mx-3 cursor-pointer border-t border-border/40 px-3 py-1 first:border-t-0 hover:bg-muted/50', selected === f.key && 'bg-primary/10', toCheck(f.key) && selected !== f.key && 'bg-warning/5')}
              data-testid={`side-field-${f.key}`}
              data-needs-review={toCheck(f.key) ? 'true' : 'false'}
            >
              <FieldRow
                className="border-t-0 py-0"
                label={f.label}
                value={empty ? undefined : String(value)}
                emptyHint={scored?.rejected ? `Read but rejected: ${String(scored.extractedValue ?? '')}` : 'Not on the page'}
                adornment={
                  toCheck(f.key) ? (
                    <Badge variant="outline" className="border-warning/50 text-warning-text">
                      Check
                    </Badge>
                  ) : empty ? null : scored?.corrected ? (
                    <Badge variant="secondary">Corrected</Badge>
                  ) : (
                    <ConfidenceBadge value={scored?.confidence} />
                  )
                }
              />
              {quote && (
                <p className="truncate pb-1 pl-[7.5rem] text-xs text-muted-foreground italic" title={quote}>
                  {scored?.citation?.page != null ? `p. ${scored.citation.page} · ` : ''}“{quote}”
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
