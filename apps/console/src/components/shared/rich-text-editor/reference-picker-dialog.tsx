'use client';

import * as React from 'react';

import { KIND_ICON } from '@/components/shared/reference-kinds';
import { SearchAddDialog } from '@/components/shared/search-add-dialog';
import { Badge } from '@/components/ui/badge';
import { useReferencePicker } from '@/hooks/references-queries';
import type { RefKind, ReferenceContext, ReferenceItem } from '@/lib/types/references';

const NOUN: Record<'tool' | 'knowledge' | 'skill', string> = { tool: 'tool', knowledge: 'knowledge source', skill: 'skill' };

export type InsertableKind = keyof typeof NOUN;

/** Insert a tool, knowledge source or skill: searched on the server, with its full context shown before it is written in. */
export function ReferencePickerDialog({ kind, context, open, onOpenChange, onPick }: { kind: InsertableKind; context: ReferenceContext; open: boolean; onOpenChange: (open: boolean) => void; onPick: (item: ReferenceItem) => void }) {
  const [search, setSearch] = React.useState('');
  React.useEffect(() => {
    if (open) setSearch('');
  }, [open]);
  const query = useReferencePicker(context, kind as RefKind, search, open);
  const noun = NOUN[kind];
  return (
    <SearchAddDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Insert a ${noun}`}
      description="It is written into the text as a badge that keeps its name."
      searchLabel={`Search ${noun}s`}
      what={`${noun}s`}
      search={search}
      onSearchChange={setSearch}
      query={query}
      empty={`This team has no ${noun}s yet. A builder can add one in Apps.`}
      rowKey={(i) => `${i.kind}:${i.id}`}
      rowTitle={(i) => i.label}
      rowDescription={(i) => i.hint}
      preview={(i) => <ReferencePreview item={i} noun={noun} />}
      addLabel="Insert"
      canAdd={(i) => !i.disabled}
      onAdd={async (i) => {
        onPick(i);
        onOpenChange(false);
      }}
      testId="reference-picker"
    />
  );
}

function ReferencePreview({ item, noun }: { item: ReferenceItem; noun: string }) {
  const Icon = KIND_ICON[item.kind];
  return (
    <div className="flex flex-col gap-3" data-testid="reference-picker-preview-body">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0">
          <h3 className="text-sm font-semibold break-words">{item.label}</h3>
          <p className="text-xs text-muted-foreground">{noun}</p>
        </div>
      </div>
      {item.hint && <p className="text-sm break-words">{item.hint}</p>}
      <div className="flex flex-wrap gap-1">
        {item.held === true && <Badge variant="secondary">Already on this {item.kind === 'skill' ? 'agent' : 'agent or skill'}</Badge>}
        {item.held === false && <Badge variant="outline">Not added yet</Badge>}
        {item.needsApproval && <Badge variant="outline">Writes need approval</Badge>}
      </div>
      {item.adds && <p className="text-xs text-muted-foreground">{item.adds}</p>}
      {item.disabled && <p className="text-xs text-destructive-text">{item.disabled}</p>}
    </div>
  );
}
