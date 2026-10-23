'use client';

import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { RecordCard } from '@/components/chat/record-cards';
import { ToolCallCard } from '@/components/chat/tool-call-card';
import { Skeleton } from '@/components/ui/skeleton';
import type { ToolCall } from '@/lib/types/chat';
import type { OpsCardRef } from '@/lib/types/ops-card';

const OPS_SERVER = 'ops';
const KINDS = new Set(['case', 'task', 'run', 'start']);

/** The card references on an Ops tool call's answer, as the thread read filled them in; null for any other call. */
export function opsCards(call: ToolCall): OpsCardRef[] | null {
  if (call.server !== OPS_SERVER || typeof call.output !== 'object' || call.output === null) return null;
  const cards = (call.output as { cards?: unknown }).cards;
  if (!Array.isArray(cards)) return null;
  return cards.filter((c): c is OpsCardRef => !!c && typeof c === 'object' && KINDS.has((c as OpsCardRef).type) && typeof (c as OpsCardRef).id === 'string');
}

/**
 * An Ops tool call drawn as what it found (c-469): its cards, then the call itself, collapsed, for whoever wants to see
 * what the agent asked. After a press the thread is read again, so every card redraws from its record's new state.
 */
export function OpsCallCards({ call, cards, readOnly }: { call: ToolCall; cards: OpsCardRef[]; readOnly?: boolean }) {
  const qc = useQueryClient();
  const reread = React.useCallback(() => void qc.invalidateQueries({ queryKey: ['chat', 'thread'] }), [qc]);
  // A reply streamed live carries the references before any thread read filled them in; reading the thread once more
  // draws them, and until then each shows as loading rather than as missing.
  const unfilled = cards.some((c) => c.view == null && !c.missing);
  React.useEffect(() => {
    if (unfilled && call.status !== 'running') reread();
  }, [unfilled, call.status, reread]);
  return (
    <div className="flex flex-col gap-2" data-testid="ops-call-cards">
      {cards.map((c) =>
        c.view == null && !c.missing ? (
          <Skeleton key={`${c.type}-${c.id}`} className="h-32 w-full rounded-xl" data-testid="ops-card-loading" />
        ) : (
          <RecordCard key={`${c.type}-${c.id}`} cardRef={c} readOnly={readOnly} onActed={reread} />
        ),
      )}
      <ToolCallCard call={call} />
    </div>
  );
}
