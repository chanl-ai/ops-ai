'use client';

import * as React from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ConfidenceBadge } from '@/components/status-badges';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';
import { useCreateDocumentType } from '@/hooks/document-type-queries';
import { plural } from '@/lib/format';
import type { DocumentField } from '@/lib/types/document-types';
import type { Extraction, ExtractionProposal } from '@/lib/types/extractions';

const KEY = /^[a-z][a-z0-9_]{0,63}$/;
/** "debtor_name" as a label: "Debtor name". */
const labelOf = (key: string) => (key.charAt(0).toUpperCase() + key.slice(1)).replace(/_/g, ' ');
const baseName = (fileName: string) => fileName.replace(/\.[^.]+$/, '');

/** What the read says about itself: proposed by the model, and how many pages it read. */
function readLine(read: Extraction): string {
  const pages = read.readPages ?? (typeof read.pages === 'number' ? read.pages : null);
  return `Fields proposed by the model${pages ? ` · ${plural(pages, 'page')} read` : ''}`;
}

/**
 * A read whose fields the model proposed: each field's name is editable beside the value read for it, and Save as
 * document type saves the fields, with the names as edited, as the team's new type with this file as its first sample.
 */
export function ProposedRead({ read, proposal, fileName }: { read: Extraction; proposal: ExtractionProposal; fileName: string }) {
  const create = useCreateDocumentType();
  const [keys, setKeys] = React.useState(() => proposal.fields.map((f) => f.key));
  const [name, setName] = React.useState(() => proposal.name || baseName(fileName));
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState<{ id: string; name: string } | null>(null);
  const record = read.records?.[0]?.fields ?? read.fields ?? {};

  const keyError = (k: string, i: number) =>
    !KEY.test(k) ? 'Lowercase letters, digits and underscores, starting with a letter.' : keys.some((o, j) => j !== i && o === k) ? 'Another field has this name.' : undefined;
  const invalid = keys.some((k, i) => keyError(k, i)) || !name.trim();

  const save = async () => {
    setError(null);
    const fields: DocumentField[] = proposal.fields.map((f, i) => (keys[i] === f.key ? f : { ...f, key: keys[i], label: labelOf(keys[i]) }));
    try {
      const t = await create.mutateAsync({ name: name.trim(), fields, sampleFileId: read.fileId });
      setSaved({ id: t.id, name: t.name });
      toast.success(`Saved ${t.name}`, { position: 'top-center', description: `${fileName} is its first sample.` });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="proposed-read">
      <p className="text-xs text-muted-foreground" data-testid="proposed-read-line">
        {readLine(read)}
      </p>
      {read.partial && (
        <Alert data-testid="proposed-read-partial">
          <AlertDescription>
            Stopped at the token limit{read.readPages ? ` after page ${read.readPages}` : ''}. Fields on later pages were not read.
          </AlertDescription>
        </Alert>
      )}
      {proposal.fields.length === 0 ? (
        <p className="rounded-lg border p-6 text-sm text-muted-foreground">The model proposed no fields for this file. Extract again with a hint saying what it is.</p>
      ) : (
        <div className="rounded-lg border">
          {proposal.fields.map((f, i) => {
            const scored = record[f.key];
            const value = scored?.value;
            const empty = value === null || value === undefined || value === '';
            const quote = scored?.citation?.quote;
            const err = keyError(keys[i], i);
            return (
              <div key={f.key} className="flex flex-col gap-2 border-t px-3 py-2.5 first:border-t-0 sm:flex-row sm:items-start">
                <div className="flex min-w-0 flex-col gap-1 sm:w-56 sm:shrink-0">
                  <Input
                    value={keys[i]}
                    onChange={(e) => setKeys((k) => k.map((x, j) => (j === i ? e.target.value : x)))}
                    aria-label={`Name of the field proposed as ${f.label ?? f.key}`}
                    aria-invalid={!!err}
                    disabled={!!saved}
                    className="h-8 font-mono text-xs"
                    data-testid="proposed-field"
                  />
                  {err && <p className="text-xs text-destructive">{err}</p>}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className={empty ? 'text-muted-foreground' : 'break-words'}>{empty ? 'Not on the pages read' : String(value)}</span>
                    {!empty && <ConfidenceBadge value={scored?.confidence} />}
                  </div>
                  {quote && (
                    <p className="truncate text-xs text-muted-foreground italic" title={quote}>
                      {scored?.citation?.page != null ? `p. ${scored.citation.page} · ` : ''}“{quote}”
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {proposal.fields.length > 0 &&
        (saved ? (
          <Alert data-testid="proposed-read-saved">
            <AlertDescription className="block">
              Saved as{' '}
              <Link href={`/document-types/${encodeURIComponent(saved.id)}`} className="font-medium underline underline-offset-2">
                {saved.name}
              </Link>
              , with this file as its first sample.
            </AlertDescription>
          </Alert>
        ) : (
          <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3 sm:flex-row sm:items-end">
            <FormField id="proposed-type-name" label="Document type name" className="min-w-0 flex-1" error={error ?? undefined}>
              <Input id="proposed-type-name" value={name} onChange={(e) => (setName(e.target.value), setError(null))} maxLength={200} placeholder="e.g. Supplier invoice" aria-invalid={!!error} data-testid="proposed-type-name" />
            </FormField>
            <LoadingButton onClick={save} isLoading={create.isPending} loadingText="Saving…" disabled={invalid} data-testid="save-document-type">
              Save as document type
            </LoadingButton>
          </div>
        ))}
    </div>
  );
}
