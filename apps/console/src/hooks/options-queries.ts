'use client';

import * as React from 'react';
import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { OptionsPage, OptionsParams, WorkflowFilters } from '@/lib/types/query';
import type { SkillLoading } from '@/lib/types/skills';

/** One picker's source: a cache key and the `/options` call behind it. */
export interface OptionSource {
  key: string;
  fetch: (p: OptionsParams) => Promise<OptionsPage>;
}

export const knowledgeBaseOptions: OptionSource = { key: 'kb-options', fetch: (p) => api.knowledge.kbs.options(p) };
export const toolOptions: OptionSource = { key: 'tool-options', fetch: (p) => api.agents.toolOptions(p) };
/** The team's files in Files; one not scanned clean is shown disabled with the reason. */
export const fileOptions: OptionSource = { key: 'file-options', fetch: (p) => api.files.options(p) };
/** The team's active people, by email: who a task is sent to. */
export const peopleOptions: OptionSource = { key: 'people-options', fetch: (p) => api.settings.members.options(p) };
/** The team's workflows (both engines) under `filters`, searched and paged by the workflows list route; a page number is the cursor. */
const workflowsWhere = (key: string, filters: WorkflowFilters = {}): OptionSource => ({
  key,
  fetch: async ({ search, cursor, limit = 25, ids }) => {
    const page = Number(cursor ?? 1);
    const res = await api.workflows.list({ page, pageSize: limit, search: ids?.length ? undefined : search, filters });
    const rows = ids?.length ? res.data.filter((w) => ids.includes(w.id)) : res.data;
    return {
      data: rows.map((w) => ({ id: w.id, label: w.name, hint: w.status === 'live' ? null : w.status })),
      nextCursor: !ids?.length && res.pagination.hasNext ? String(page + 1) : null,
    };
  },
});
/** Every workflow of the team. */
export const workflowOptions = workflowsWhere('workflow-options');
/** Workflows a person may start by hand: those only other workflows start are left out (c-466). */
export const startableWorkflowOptions = workflowsWhere('workflow-options:startable', { startable: ['true'] });
/** Workflows a file can start: an email trigger, or a form with a file field; never one only other workflows start. */
export const fileWorkflowOptions = workflowsWhere('workflow-options:files', { startable: ['true'], takesFiles: ['true'] });
export const guardrailOptions: OptionSource = { key: 'guardrail-options', fetch: (p) => api.guardrails.options(p) };
/** Widgets, disabled with the reason when a button needs a tool outside `granted` (the draft's tools). */
export const widgetOptionsFor = (granted: string[]): OptionSource => ({ key: `widget-options:${[...granted].sort().join(',')}`, fetch: (p) => api.widgets.options(p, granted) });
/** Skills the agent may attach; `loading` keeps always-on or on-match ones. */
export const skillOptionsFor = (agentId: string, loading?: SkillLoading): OptionSource => ({ key: `skill-options:${agentId}:${loading ?? 'all'}`, fetch: (p) => api.skills.agents.options(agentId, p, loading) });

/** Pages of a source's options for a search, one page at a time as the list scrolls; the search runs on the server. */
export function useOptionSearch(source: OptionSource, search: string, enabled: boolean, limit = 25) {
  const [debounced, setDebounced] = React.useState(search);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 200);
    return () => clearTimeout(t);
  }, [search]);
  return useInfiniteQuery({
    queryKey: [source.key, 'search', debounced, limit],
    queryFn: ({ pageParam }) => source.fetch({ search: debounced, cursor: pageParam, limit }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Labels for stored ids, asked of the service by id rather than found in a list the browser loaded. */
export function useOptionLabels(source: OptionSource, ids: string[]) {
  const sorted = [...ids].sort();
  return useQuery({
    queryKey: [source.key, 'labels', sorted],
    queryFn: () => source.fetch({ ids: sorted, limit: Math.max(sorted.length, 1) }),
    enabled: sorted.length > 0,
    staleTime: 60_000,
  });
}
