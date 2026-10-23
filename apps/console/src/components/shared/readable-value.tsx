'use client';

import * as React from 'react';
import Link from 'next/link';
import { Braces } from 'lucide-react';

import { FieldRow } from '@/components/shared/field-row';
import { JsonBlock } from '@/components/shared/json-block';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { count, fieldValue, plural } from '@/lib/format';

/** A key as a label: `caseNo` and `case_no` both read "Case no". */
export const labelOf = (key: string) => key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

// A value that is a file's or a run's id links to its page, whatever the field is called.
const FILE_ID = /^fil_[A-Za-z0-9]+$/;
const RUN_ID = /^wfrun_[A-Za-z0-9]+$/;
// Nested objects deeper than this show as their count of fields; the Raw view has the rest.
const MAX_DEPTH = 3;
const MAX_ITEMS = 5;

const empty = (v: unknown) => v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length) || (typeof v === 'object' && v !== null && !Array.isArray(v) && !Object.keys(v).length);

/** One value as it reads: calendar dates formatted, numbers grouped, a file id as a link; the key never decides. */
export function PlainValue({ value }: { value: unknown }) {
  if (typeof value === 'string' && FILE_ID.test(value))
    return (
      <Link href={`/files/${encodeURIComponent(value)}`} className="underline underline-offset-2">
        Open the file
      </Link>
    );
  if (typeof value === 'number') return <>{count(value)}</>;
  if (typeof value === 'string') return <>{fieldValue(value)}</>;
  return <>{JSON.stringify(value)}</>;
}

/** A leaf of a readable value: a run id links to its run and a yes or no reads as words, beside what PlainValue does. */
function Leaf({ value }: { value: unknown }) {
  if (typeof value === 'string' && RUN_ID.test(value))
    return (
      <Link href={`/workflows/runs/${encodeURIComponent(value)}`} className="underline underline-offset-2">
        Open the run
      </Link>
    );
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>;
  if (typeof value === 'number') return <span className="tabular-nums">{count(value)}</span>;
  if (typeof value === 'string') return <span className="break-words whitespace-pre-wrap">{FILE_ID.test(value) ? <PlainValue value={value} /> : fieldValue(value)}</span>;
  return <PlainValue value={value} />;
}

function Fields({ value, depth }: { value: Record<string, unknown>; depth: number }) {
  const rows = Object.entries(value).filter(([, v]) => !empty(v));
  if (!rows.length) return <span className="text-muted-foreground">Nothing</span>;
  return (
    <div className={depth ? 'border-l pl-3' : undefined}>
      {rows.map(([key, v]) => (
        <FieldRow key={key} label={labelOf(key)} value={<Readable value={v} depth={depth + 1} />} wrap />
      ))}
    </div>
  );
}

function Readable({ value, depth }: { value: unknown; depth: number }) {
  if (empty(value)) return <span className="text-muted-foreground">Nothing</span>;
  if (Array.isArray(value)) {
    if (value.every((v) => v === null || typeof v !== 'object')) return <Leaf value={value.filter((v) => !empty(v)).join(', ')} />;
    if (depth >= MAX_DEPTH) return <>{plural(value.length, 'item')}</>;
    return (
      <div className="flex flex-col gap-2">
        {value.slice(0, MAX_ITEMS).map((v, i) => (
          <Readable key={i} value={v} depth={depth} />
        ))}
        {value.length > MAX_ITEMS && <span className="text-xs text-muted-foreground">and {value.length - MAX_ITEMS} more</span>}
      </div>
    );
  }
  if (typeof value === 'object' && value !== null) {
    if (depth >= MAX_DEPTH) return <>{plural(Object.keys(value).length, 'field')}</>;
    return <Fields value={value as Record<string, unknown>} depth={depth} />;
  }
  return <Leaf value={value} />;
}

/**
 * Any JSON value as labelled fields a person reads, with the JSON one click away under Raw. Built from the value's
 * shape alone, so a workflow's input, output or result reads the same whatever the workflow.
 */
export function ReadableValue({ value, testId, rawOnly }: { value: unknown; testId?: string; /** Another view on the page tells it already: only the Raw toggle shows. */ rawOnly?: boolean }) {
  const [raw, setRaw] = React.useState(false);
  return (
    <Collapsible open={raw} onOpenChange={setRaw} className="flex min-w-0 flex-col gap-2" data-testid={testId}>
      {!raw && !rawOnly && <Readable value={value} depth={0} />}
      <CollapsibleContent>
        <JsonBlock value={value ?? null} />
      </CollapsibleContent>
      <CollapsibleTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="w-fit text-muted-foreground" data-testid={testId ? `${testId}-raw` : undefined}>
          <Braces /> {raw ? 'Show as fields' : 'Raw'}
        </Button>
      </CollapsibleTrigger>
    </Collapsible>
  );
}
