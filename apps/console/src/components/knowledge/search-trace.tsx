'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { AlertTriangle, BadgeCheck, MinusCircle } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { count, ms } from '@/lib/format';
import type { PlaygroundAnswer, RetrievalSettings, SearchPassage } from '@/lib/types/knowledge';

const LANE: Record<string, string> = { keyword: 'Keyword', meaning: 'Meaning' };
const laneWord = (l: string) => LANE[l] ?? l;
const MATCHED: Record<string, string> = { self: 'Piece text', question: 'Question', faq: 'FAQ pair', child: 'Part of the piece' };

/** Why a lane was skipped, in words; the code itself follows for anything else. */
function skipReason(reason: string) {
  if (reason === 'no_embedding_model') return 'no embedding model is set for this installation';
  if (reason === 'no_vector_store') return 'this installation keeps no vectors';
  if (reason === 'no_vectors') return 'no piece of this base is embedded yet';
  if (reason.startsWith('embedding_unavailable')) return `embedding the question failed (${reason.split(':').slice(1).join(':').trim() || 'unavailable'})`;
  return reason;
}

const score = (n: number | undefined) => (n === undefined ? '—' : n.toFixed(n < 0.1 ? 4 : 2));

const COLUMNS: ColumnDef<SearchPassage>[] = [
  {
    id: 'piece',
    header: 'Piece',
    cell: ({ row }) => (
      <div className="max-w-sm min-w-56 whitespace-normal">
        <div className="font-medium">{row.original.section || row.original.title}</div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          {row.original.title} · {row.original.version}
          {row.original.page ? ` · page ${row.original.page}` : ''}
          {row.original.verified && <BadgeCheck className="size-3 text-success-text" aria-label="Verified" />}
        </div>
      </div>
    ),
  },
  { id: 'matched', header: 'Best match', cell: ({ row }) => <span className="text-sm whitespace-nowrap">{MATCHED[row.original.matched ?? 'self'] ?? row.original.matched}</span> },
  { id: 'keyword', header: 'Keyword', cell: ({ row }) => <span className="tabular-nums">{score(row.original.lanes?.keyword)}</span> },
  { id: 'meaning', header: 'Meaning', cell: ({ row }) => <span className="tabular-nums">{score(row.original.lanes?.meaning)}</span> },
  { id: 'fused', header: 'Fused', cell: ({ row }) => <span className="font-medium tabular-nums">{score(row.original.score)}</span> },
];

/**
 * What one search of a base did, as kb-service reports it: the lanes asked, run and skipped with the reason, each
 * passage's score per lane and fused, and the embedding tokens the question cost. Nothing here is worked out in the
 * browser; the settings line is the base's own saved retrieval.
 */
export function SearchTrace({ result, settings }: { result: PlaygroundAnswer; settings: RetrievalSettings }) {
  const lanes = result.lanes ?? { asked: [], ran: [], skipped: [] };
  const passages = result.passages ?? [];
  const onlyLane = lanes.skipped.length > 0 && lanes.ran.length === 1 ? lanes.ran[0] : null;
  return (
    <div className="flex flex-col gap-3" data-testid="search-trace">
      <div className="flex flex-col gap-2 rounded-md border bg-muted/20 p-3">
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Lanes</span>
          {lanes.asked.map((l) => {
            const skipped = lanes.skipped.find((s) => s.lane === l);
            return lanes.ran.includes(l) ? (
              <Badge key={l} variant="secondary" className="font-normal">
                {laneWord(l)} ran
              </Badge>
            ) : (
              <Badge key={l} variant="outline" className="border-warning/40 bg-warning/10 font-normal text-warning-text" title={skipped ? skipReason(skipped.reason) : undefined}>
                {laneWord(l)} skipped
              </Badge>
            );
          })}
          <span className="text-xs text-muted-foreground">
            {settings.searchMode === 'hybrid' ? `fused by rank · weight ${settings.hybridWeight} toward meaning · ` : ''}threshold {settings.threshold} · limit {settings.chunkLimit}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>{count(result.cost?.embeddingTokens ?? 0)} embedding tokens for the question</span>
          <span>Searched in {ms(result.retrievalMs)}</span>
        </div>
      </div>

      {onlyLane && (
        <Alert data-testid="search-lane-skipped">
          <AlertTriangle className="size-4" />
          <AlertTitle>{laneWord(onlyLane)} search only for this question</AlertTitle>
          <AlertDescription>
            {lanes.skipped.map((s) => `${laneWord(s.lane)} search was skipped: ${skipReason(s.reason)}.`).join(' ')} Results come from the {laneWord(onlyLane).toLowerCase()} lane.
          </AlertDescription>
        </Alert>
      )}

      {passages.length === 0 ? (
        <Alert>
          <MinusCircle className="size-4" />
          <AlertTitle>No passage passed the threshold</AlertTitle>
          <AlertDescription>Nothing in this knowledge base scored {settings.threshold} or more in a lane. An agent says its no-answer message.</AlertDescription>
        </Alert>
      ) : (
        <DataTableWithViews columns={COLUMNS} data={passages} getRowId={(p) => `${p.itemId}-${p.section}-${p.score}`} hideViewSwitcher hidePaginationOnOnePage rowNoun="passage" />
      )}
    </div>
  );
}
