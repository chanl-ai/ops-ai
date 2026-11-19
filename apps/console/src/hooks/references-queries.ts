'use client';

import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { RefKind, ReferenceContext, ReferenceItem, ReferenceSearch } from '@/lib/types/references';

import { teamKey, useTeamQuery } from './team-query';

const REFERENCES = ['references'] as const;
const of = (context: ReferenceContext) => ('forAgent' in context ? `agent:${context.forAgent}` : `skill:${context.forSkill}`);

/**
 * The search an instruction document's `@` menu calls for the text typed after it. Each answer is kept for half a
 * minute under the team, the document's owner and the text, so typing back over a word asks nothing new.
 */
export function useReferenceSearch(context: ReferenceContext): (query: string, kind?: RefKind) => Promise<ReferenceSearch> {
  const client = useQueryClient();
  const owner = of(context);
  return React.useCallback(
    // Not asked again on failure: the menu says the search failed at once, and the next letter typed asks again.
    (query, kind) => client.fetchQuery({ queryKey: teamKey([...REFERENCES, owner, 'search', query, kind ?? '']), queryFn: () => api.references.search(context, { search: query, kind }), staleTime: 30_000, retry: false }),
    // `owner` stands for `context`, which callers build inline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, owner],
  );
}

/** The current names of a document's references (`kind:id` each). An id the answer leaves out is missing. */
export function useReferenceLabels(context: ReferenceContext, ids: string[]) {
  return useTeamQuery({
    queryKey: [...REFERENCES, of(context), 'labels', ids],
    queryFn: () => api.references.labels(context, ids),
    select: (found): ReferenceItem[] => found.groups.flatMap((g) => g.items),
    enabled: ids.length > 0,
    // The chips keep their names while a changed document asks again.
    placeholderData: (previous) => previous,
  });
}
