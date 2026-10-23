'use client';

import * as React from 'react';
import Link from 'next/link';
import { Check, ChevronRight, FileText, Mail } from 'lucide-react';

import { Row, Rows } from '@/components/shared/surface';
import { ConfidenceBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { pct } from '@/lib/format';
import type { DocumentRead, FieldRead, ReadField, ReplyPreview } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

/** A reviewer's corrections, by record index then field key, as typed. */
export type ReadEdits = Record<number, Record<string, string>>;
/** Key fields a reviewer has confirmed, by record index. */
export type ReadConfirmed = Record<number, string[]>;

/** How many key fields are still to confirm across the records; 0 when the type marks none. */
export function keyFieldsLeft(read: DocumentRead, confirmed: ReadConfirmed): number {
  const keys = read.schema.filter((f) => f.keyField).map((f) => f.key);
  return read.records.reduce((n, _, i) => n + keys.filter((k) => !confirmed[i]?.includes(k)).length, 0);
}

/** What Approve waits for while key fields are unconfirmed ("confirm 2 key fields first"); undefined when nothing does. */
export function keyFieldsBlock(read: DocumentRead | null | undefined, confirmed: ReadConfirmed): string | undefined {
  const left = read ? keyFieldsLeft(read, confirmed) : 0;
  return left ? `confirm ${left === 1 ? '1 key field' : `${left} key fields`} first` : undefined;
}

/** Key-field confirmations and the way to toggle one, passed together. */
export interface ReadChecks {
  confirmed: ReadConfirmed;
  onConfirm: (record: number, key: string) => void;
}

/** The key-field confirmations of the open review, cleared when another review opens. */
export function useReadConfirmations(reviewId: string | undefined): ReadChecks {
  const [confirmed, setConfirmed] = React.useState<ReadConfirmed>({});
  React.useEffect(() => {
    setConfirmed({});
  }, [reviewId]);
  const onConfirm = React.useCallback(
    (record: number, key: string) => setConfirmed((c) => ({ ...c, [record]: c[record]?.includes(key) ? c[record].filter((k) => k !== key) : [...(c[record] ?? []), key] })),
    [],
  );
  return { confirmed, onConfirm };
}

const shown = (v: unknown) => (v === null || v === undefined ? '' : String(v));

const isMoney = (field: ReadField | undefined) => field?.type === 'money';

/** A field's value as the reviewer reads and types it: money to two decimals, everything else as it is. */
function asText(field: ReadField | undefined, v: unknown): string {
  if (isMoney(field) && typeof v === 'number') return v.toFixed(2);
  return shown(v);
}

/** What a typed correction sends: numbers and money as numbers, an emptied field as null, everything else as text. */
function typed(field: ReadField | undefined, text: string): unknown {
  if (!text.trim()) return null;
  if (field && (field.type === 'number' || field.type === 'money')) {
    const n = Number(text.replace(/[^\d.-]/g, ''));
    return Number.isFinite(n) ? n : text;
  }
  return text;
}

/** The whole records list Approve sends as `inputs.edited`: each record's values with the reviewer's changes; untouched values go back as read. */
export function correctedRecords(read: DocumentRead, edits: ReadEdits): { values: Record<string, unknown> }[] {
  const byKey = new Map(read.schema.map((f) => [f.key, f]));
  return read.records.map((r, i) => {
    const changed = Object.fromEntries(Object.entries(edits[i] ?? {}).map(([k, text]) => [k, typed(byKey.get(k), text)]));
    return { values: { ...r.values, ...changed } };
  });
}

/** True when any typed value differs from what was read. */
export function hasCorrections(read: DocumentRead, edits: ReadEdits): boolean {
  const byKey = new Map(read.schema.map((f) => [f.key, f]));
  return read.records.some((r, i) => Object.entries(edits[i] ?? {}).some(([k, text]) => text !== asText(byKey.get(k), r.values[k])));
}

/** Where a field came from: its page and quote. `onOpen` is the slot for opening the document at that spot (c-237); without it the source is text. */
function SourceCell({ citation, onOpen }: { citation: FieldRead['citation']; onOpen?: () => void }) {
  if (!citation || (citation.page == null && !citation.quote)) return <span className="text-xs text-muted-foreground">—</span>;
  const text = (
    <>
      {citation.page != null && <span className="shrink-0 tabular-nums">p. {citation.page}</span>}
      {citation.quote && <span className="min-w-0 break-words italic">“{citation.quote}”</span>}
    </>
  );
  return onOpen ? (
    <button type="button" onClick={onOpen} className="flex max-w-full items-baseline gap-1.5 text-left text-xs text-muted-foreground underline-offset-2 hover:underline">
      {text}
    </button>
  ) : (
    <span className="flex max-w-full items-baseline gap-1.5 text-xs text-muted-foreground" title={citation.quote ?? undefined}>
      {text}
    </span>
  );
}

function RecordTable({
  read,
  tabbed,
  index,
  editing,
  edits,
  onEdit,
  onOpenSource,
  confirmed = [],
  onConfirm,
}: {
  read: DocumentRead;
  index: number;
  editing: boolean;
  edits: Record<string, string>;
  onEdit: (key: string, text: string) => void;
  confirmed?: string[];
  onConfirm?: (key: string) => void;
  onOpenSource?: (field: string) => void;
  tabbed?: boolean }) {
  const record = read.records[index];
  const corrected = read.corrected?.[index];
  // Fields that need a check come first, then the rest in the workflow's own order.
  const fields = [...read.schema].sort((a, b) => Number(!!record.fields[b.key]?.needsReview) - Number(!!record.fields[a.key]?.needsReview));
  const title = shown(record.values.name) || `Record ${index + 1}`;
  // The currency a money field is in, when the read has one; never a guessed code.
  const currency = shown(record.values.currency) || null;
  const sources = read.sources ?? [];
  const keyFields = fields.filter((f) => f.keyField);
  // With no key fields marked, the values in doubt come first and the confident rest are accepted together.
  const doubtful = keyFields.length ? [] : fields.filter((f) => record.fields[f.key]?.needsReview && !record.fields[f.key]?.corrected);
  const others = fields.filter((f) => !(keyFields.length ? f.keyField : doubtful.includes(f)));
  const [accepted, setAccepted] = React.useState(false);
  const renderRow = (f: ReadField, confirm?: React.ReactNode) => {
            const scored = record.fields[f.key];
            const asRead = asText(f, record.values[f.key]);
            const text = edits[f.key] ?? asRead;
            const fixed = editing ? text !== asRead : corrected !== undefined && asText(f, corrected[f.key]) !== asRead;
            // Nothing read means nothing to be confident about: the row says so and shows no confidence.
            const missing = asRead === '';
            // A person's correction settles the field, whatever the read thought of it.
            const check = !!scored?.needsReview && !scored?.corrected;
            return (
              <TableRow key={f.key} data-testid={`read-field-${index}-${f.key}`} data-needs-review={check ? 'true' : 'false'} className={cn(check && 'bg-warning/5')}>
                <TableCell className="align-top text-sm whitespace-normal">
                  {/* The label is quieter than the value; confidence is a small badge, and a field to check says so. */}
                  <span className="flex flex-col gap-1.5">
                    <span className="text-muted-foreground">{f.label}</span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      {!missing && !scored?.corrected && <ConfidenceBadge value={scored?.confidence} />}
                      {check && (
                        <Badge variant="outline" className="w-fit border-warning/50 text-warning-text">
                          Check
                        </Badge>
                      )}
                      {scored?.conflict && (
                        <Badge variant="outline" className="w-fit border-destructive/50 text-destructive" data-testid={`read-differs-${index}-${f.key}`}>
                          Differs
                        </Badge>
                      )}
                      {confirm}
                    </span>
                  </span>
                </TableCell>
                <TableCell className="align-top whitespace-normal">
                  {editing ? (
                    isMoney(f) && currency ? (
                      // An amount with its currency after it, as money() writes it; with none read, the bare amount.
                      <InputGroup className="h-8 min-w-36">
                        <InputGroupInput value={text} onChange={(e) => onEdit(f.key, e.target.value)} inputMode="decimal" aria-label={`${f.label} for ${title}`} className="tabular-nums" data-testid={`read-input-${index}-${f.key}`} />
                        <InputGroupAddon align="inline-end">
                          <InputGroupText>{currency}</InputGroupText>
                        </InputGroupAddon>
                      </InputGroup>
                    ) : (
                      <Input value={text} onChange={(e) => onEdit(f.key, e.target.value)} inputMode={isMoney(f) ? 'decimal' : undefined} aria-label={`${f.label} for ${title}`} className={cn('h-8 min-w-36', isMoney(f) && 'tabular-nums')} data-testid={`read-input-${index}-${f.key}`} />
                    )
                  ) : (
                    <span className="text-sm break-words">{fixed ? asText(f, corrected?.[f.key]) : asRead || <span className="text-muted-foreground">{scored?.rejected ? `Read but rejected: ${shown(scored.extractedValue)}` : 'Not on the page'}</span>}</span>
                  )}
                  {fixed && (
                    <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid={`read-corrected-${index}-${f.key}`}>
                      <Badge variant="secondary">Corrected</Badge> read as {asRead ? `“${asRead}”` : 'nothing'}
                    </span>
                  )}
                  {/* On a phone the source sits under the value; from sm up it has its own column. */}
                  <span className="mt-1.5 block sm:hidden">
                    <SourceCell citation={scored?.citation ?? null} onOpen={onOpenSource ? () => onOpenSource(f.key) : undefined} />
                  </span>
                </TableCell>
                <TableCell className="hidden align-top whitespace-normal sm:table-cell">
                  <SourceCell citation={scored?.citation ?? null} onOpen={onOpenSource ? () => onOpenSource(f.key) : undefined} />
                </TableCell>
                {sources.map((name) => (
                  // Each source's own value beside the one the read kept, so a disagreement is read, not guessed.
                  <TableCell key={name} className="hidden align-top text-sm whitespace-normal sm:table-cell" data-testid={`read-source-${index}-${f.key}-${name}`}>
                    {scored?.bySource && name in scored.bySource ? asText(f, scored.bySource[name]) || '—' : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                ))}
              </TableRow>
            );
  };
  // One header for every table of a record, key fields included, so each column is named wherever it starts.
  const head = (
    <TableHeader>
      <TableRow>
        <TableHead className="w-28">Field</TableHead>
        <TableHead>Value</TableHead>
        <TableHead className="hidden sm:table-cell">Source</TableHead>
        {sources.map((name) => (
          <TableHead key={name} className="hidden sm:table-cell">
            {name.charAt(0).toUpperCase() + name.slice(1)}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  );
  const table = (rows: ReadField[], testId?: string) => (
    <Table data-testid={testId}>
      {head}
      <TableBody>{rows.map((f) => renderRow(f))}</TableBody>
    </Table>
  );
  const confirmedCount = keyFields.filter((f) => confirmed.includes(f.key)).length;
  // A doubtful field folded under the others still says it is there.
  const toCheck = others.filter((f) => record.fields[f.key]?.needsReview && !record.fields[f.key]?.corrected).length;
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3" data-testid={`read-record-${index}`}>
      {/* Under a tab the tab names the record already. */}
      {!tabbed && <p className="text-sm font-medium">{title}</p>}
      {keyFields.length > 0 && (
        // The document type marks these key: each is confirmed on its own, and Approve waits for them.
        <div className="flex flex-col gap-1" data-testid={`read-key-fields-${index}`}>
          <p className="text-xs font-medium text-muted-foreground">
            Key fields: confirm each ({confirmedCount} of {keyFields.length})
          </p>
          <Table>
            {head}
            <TableBody>
              {keyFields.map((f) =>
                renderRow(
                  f,
                  onConfirm && (
                    <Button
                      type="button"
                      size="sm"
                      variant={confirmed.includes(f.key) ? 'secondary' : 'outline'}
                      className="h-6 px-2 text-xs"
                      aria-pressed={confirmed.includes(f.key)}
                      onClick={() => onConfirm(f.key)}
                      data-testid={`read-confirm-${index}-${f.key}`}
                    >
                      {confirmed.includes(f.key) ? (
                        <>
                          <Check className="size-3" /> Confirmed
                        </>
                      ) : (
                        'Confirm'
                      )}
                    </Button>
                  ),
                ),
              )}
            </TableBody>
          </Table>
        </div>
      )}
      {doubtful.length > 0 && (
        <div className="flex flex-col gap-1" data-testid={`read-doubtful-fields-${index}`}>
          <p className="text-xs font-medium text-muted-foreground">To check ({doubtful.length})</p>
          {table(doubtful)}
        </div>
      )}
      {others.length > 0 && (keyFields.length > 0 || onConfirm) ? (
        // Folded behind key fields, which carry the decision; open when nothing is marked key, so every value is seen.
        <Collapsible defaultOpen={keyFields.length === 0} className="flex flex-col gap-1" data-testid={`read-other-fields-${index}`}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <CollapsibleTrigger className="group flex items-center gap-1 font-medium" data-testid={`read-other-toggle-${index}`}>
              <ChevronRight className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
              {keyFields.length || doubtful.length ? 'Other ' : ''}
              {others.length === 1 ? '1 field' : `${others.length} fields`}
            </CollapsibleTrigger>
            <span className="text-xs text-muted-foreground" data-testid={`read-other-summary-${index}`}>
              {keyFields.length ? `not marked key${toCheck ? ` · ${toCheck} to check` : ''}` : 'read with confidence'}
            </span>
            {onConfirm && (
              <Button type="button" size="sm" variant={accepted ? 'secondary' : 'outline'} className="ml-auto h-7" onClick={() => setAccepted((a) => !a)} aria-pressed={accepted} data-testid={`read-accept-others-${index}`}>
                {accepted ? (
                  <>
                    <Check className="size-3.5" /> Accepted
                  </>
                ) : (
                  `Accept all ${others.length}`
                )}
              </Button>
            )}
          </div>
          <CollapsibleContent>{table(others)}</CollapsibleContent>
        </Collapsible>
      ) : (
        table(others)
      )}
    </div>
  );
}

/** A document read a person checks: the file, the floor, and one table per record; values are inputs while the review is open and the step takes a correction. */
export function DocumentReadSection({
  read,
  open,
  edits,
  onEdit,
  confirmed,
  onConfirm,
  onOpenSource,
}: {
  read: DocumentRead;
  open: boolean;
  edits: ReadEdits;
  onEdit: (record: number, key: string, text: string) => void;
  /** Key-field confirmations; without `onConfirm` (a decided review, or no one to decide) no Confirm is offered. */
  confirmed?: ReadConfirmed;
  onConfirm?: (record: number, key: string) => void;
  /** Shows where a field was read on the document beside the table; without it the source is text. */
  onOpenSource?: (record: number, key: string) => void;
}) {
  const editing = open && read.editable;
  const record = (i: number) => (
    <RecordTable
      key={i}
      tabbed={read.records.length > 1}
      read={read}
      index={i}
      editing={editing}
      edits={edits[i] ?? {}}
      onEdit={(key, text) => onEdit(i, key, text)}
      confirmed={confirmed?.[i]}
      onConfirm={open && onConfirm ? (key) => onConfirm(i, key) : undefined}
      onOpenSource={onOpenSource ? (key) => onOpenSource(i, key) : undefined}
    />
  );
  const doubtful = read.records.reduce((n, r) => n + Object.values(r.fields).filter((f) => f.needsReview && !f.corrected).length, 0);
  return (
    <div className="flex flex-col gap-3" data-testid="document-read">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <Link href={`/files?file=${read.fileId}`} className="flex items-center gap-1.5 font-medium underline-offset-2 hover:underline" data-testid="read-file-link">
          <FileText className="size-4 text-muted-foreground" /> {read.fileName ?? read.fileId}
        </Link>
        <span className="text-xs text-muted-foreground">
          {read.records.length === 1 ? '1 record' : `${read.records.length} records`}
          {doubtful ? ` · ${doubtful === 1 ? '1 field' : `${doubtful} fields`} to check` : ''}
        </span>
      </div>
      {read.floor != null && <p className="text-xs text-muted-foreground">Fields under {pct(read.floor)} need a check{editing ? '. Correct a value before approving; the case opens on what you approve.' : '.'}</p>}
      {read.records.length > 1 ? (
        // One record at a time: a tab per person the document names, each with its own key fields.
        <Tabs defaultValue="0" className="gap-3" data-testid="read-record-tabs">
          <TabsList className="h-auto w-full flex-wrap justify-start">
            {read.records.map((rec, i) => (
              <TabsTrigger key={i} value={String(i)} className="flex-none" data-testid={`read-record-tab-${i}`}>
                {shown(rec.values.name) || `Record ${i + 1}`}
              </TabsTrigger>
            ))}
          </TabsList>
          {read.records.map((_, i) => (
            <TabsContent key={i} value={String(i)}>
              {record(i)}
            </TabsContent>
          ))}
        </Tabs>
      ) : (
        record(0)
      )}
    </div>
  );
}

/** The reply a review approves, as it will be sent, and the case each of the document's runs opened. */
export function ReplySection({ reply }: { reply: ReplyPreview }) {
  return (
    <div className="flex flex-col gap-3" data-testid="reply-preview">
      <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-2">
        <div className="bg-card p-3">
          <dt className="text-xs text-muted-foreground">To</dt>
          <dd className="font-medium" data-testid="reply-to">
            {reply.to}
          </dd>
        </div>
        <div className="bg-card p-3">
          <dt className="text-xs text-muted-foreground">From</dt>
          <dd className="flex items-center gap-1.5 font-medium" data-testid="reply-from">
            <Mail className="size-3.5 text-muted-foreground" /> {reply.mailbox ?? 'The workspace sender'}
          </dd>
        </div>
        <div className="bg-card p-3 sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Subject</dt>
          <dd className="font-medium">{reply.subject}</dd>
        </div>
      </dl>
      <p className="whitespace-pre-wrap rounded-lg border bg-muted/40 p-3 text-sm" data-testid="reply-body">
        {reply.body}
      </p>
      {reply.cases.length > 0 && (
        <Rows className="rounded-lg border">
          {reply.cases.map((c, i) => (
            <Row
              key={c.runId}
              title={<span className="font-normal">Debtor {i + 1}</span>}
              description={<span className="font-mono text-xs">{c.runId}</span>}
              trailing={
                c.caseId ? (
                  <Link href={`/cases/${c.caseId}`} className="text-xs underline underline-offset-2" data-testid={`reply-case-${c.runId}`}>
                    {c.caseId}
                  </Link>
                ) : (
                  <span className="text-xs text-muted-foreground" data-testid={`reply-case-${c.runId}`}>
                    Opening
                  </span>
                )
              }
            />
          ))}
        </Rows>
      )}
    </div>
  );
}
