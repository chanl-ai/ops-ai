'use client';

import * as React from 'react';
import { Brain } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useConfirmMemory, useDismissMemory } from '@/hooks/memory-queries';
import type { RememberedItem } from '@/lib/types/chat';

/**
 * One thing a reply thinks is worth keeping, asked as a quiet line under it: "Remember “Prefers tables”? Yes · No".
 * Yes keeps it (POST /v1/me/memories/{id}/confirm), No drops it (/undo); until then nothing is used. Only the memory's
 * person gets its value, so the line shows only to them.
 */
export function MemorySuggestion({ item }: { item: RememberedItem }) {
  const yes = useConfirmMemory();
  const no = useDismissMemory();
  const [answered, setAnswered] = React.useState<'kept' | 'dropped' | null>(null);
  const failed = yes.error ?? no.error;
  const busy = yes.isPending || no.isPending;
  if (!item.value) return null;
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid="memory-suggestion" aria-live="polite">
      <Brain className="size-3" />
      {answered === 'kept' ? (
        <span data-testid="memory-suggestion-kept">Remembered: {item.value}</span>
      ) : answered === 'dropped' ? (
        <span data-testid="memory-suggestion-dropped">Not remembered</span>
      ) : (
        <>
          <span>Remember “{item.value}”?</span>
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto px-0 text-xs"
            disabled={busy}
            onClick={() => yes.mutate(item.id, { onSuccess: () => setAnswered('kept') })}
            data-testid="memory-suggestion-yes"
          >
            Yes
          </Button>
          <span aria-hidden>·</span>
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto px-0 text-xs text-muted-foreground"
            disabled={busy}
            onClick={() => no.mutate(item.id, { onSuccess: () => setAnswered('dropped') })}
            data-testid="memory-suggestion-no"
          >
            No
          </Button>
          {failed && <span className="text-destructive-text">Couldn’t save your answer: {failed.message}</span>}
        </>
      )}
    </p>
  );
}
