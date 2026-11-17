'use client';

import * as React from 'react';
import { keepPreviousData } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type { ConnectionOptionsPage, OptionsPage, OptionsParams, ToolOptionsPage, WorkflowFilters } from '@/lib/types/query';
import type { SkillLoading } from '@/lib/types/skills';
import { useTeamInfiniteQuery, useTeamQuery } from './team-query';

/** One picker's source: a cache key and the `/options` call behind it; `P` is a page that carries more than options. */
export interface OptionSource<P extends OptionsPage = OptionsPage> {
  key: string;
  fetch: (p: OptionsParams) => Promise<P>;
}

export const knowledgeBaseOptions: OptionSource = { key: 'kb-options', fetch: (p) => api.knowledge.kbs.options(p) };
export const toolOptions: OptionSource<ToolOptionsPage> = { key: 'tool-options', fetch: (p) => api.agents.toolOptions(p) };
/** An MCP link's picker: the team's tools and published workflows, no agents. */
export const linkToolOptions: OptionSource<ToolOptionsPage> = { key: 'link-tool-options', fetch: (p) => api.agents.toolOptions({ ...p, agents: false }) };
/** The team's files in Files; one not scanned clean is shown disabled with the reason. */
export const fileOptions: OptionSource = { key: 'file-options', fetch: (p) => api.files.options(p) };
/** The team's active people, by email: who a task is sent to. */
export const peopleOptions: OptionSource = { key: 'people-options', fetch: (p) => api.settings.members.options(p) };
/** The team's agents, searched and paged by the agents list route; a page number is the cursor. */
export const agentOptions: OptionSource = {
  key: 'agent-options',
  fetch: async ({ search, cursor, limit = 25, ids }) => {
    const page = Number(cursor ?? 1);
    const res = await api.agents.list({ page, pageSize: limit, search: ids?.length ? undefined : search, filters: {} });
    const rows = ids?.length ? res.data.filter((a) => ids.includes(a.id)) : res.data;
    return { data: rows.map((a) => ({ id: a.id, label: a.name, hint: a.role || null })), nextCursor: !ids?.length && res.pagination.hasNext ? String(page + 1) : null };
  },
};
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
/** Workflows a person may start by hand: those only other workflows start are left out. */
export const startableWorkflowOptions = workflowsWhere('workflow-options:startable', { startable: ['true'] });
/** Workflows a file can start: an email trigger, or a form with a file field; never one only other workflows start. */
export const fileWorkflowOptions = workflowsWhere('workflow-options:files', { startable: ['true'], takesFiles: ['true'] });
/**
 * The team's apps by the id the Apps page shows (plugin:<id>, a connection's id, builtin:<id>), from GET /v1/apps,
 * which searches by name and category and names cards with `ids`; a page number is the cursor.
 */
const appsWhere = (key: string, builtin: boolean): OptionSource => ({
  key,
  fetch: async ({ search, cursor, limit = 25, ids }) => {
    const page = Number(cursor ?? 1);
    const res = await sdk((ops) =>
      ops.raw.tools.apps_list_apps({ query: { page, pageSize: ids?.length ? Math.min(ids.length, 50) : limit, ids: ids?.length ? ids : undefined, search: ids?.length ? undefined : search || undefined, include: builtin ? 'builtin' : undefined } }),
    );
    return { data: res.data.map((c) => ({ id: c.id, label: c.name, hint: c.category ?? null })), nextCursor: !ids?.length && res.pagination.hasNext ? String(page + 1) : null };
  },
});
/** The built-in apps stay pickable here (a mailbox reply is the write teams most often approve), off the Apps grid. */
export const appOptions = appsWhere('app-options', true);
/** The team's plugin apps and the apps a person added, without the built-in ones: where a step names an app's account. */
export const teamAppOptions = appsWhere('team-app-options', false);
/**
 * The apps a module may sign in through, by the id a module is bound to (the card's default account); an app with
 * none is left out of the page. `status` draws the badge a picker shows beside a name that is not healthy.
 */
export const connectionOptions: OptionSource<ConnectionOptionsPage> = {
  key: 'connection-options',
  fetch: async ({ search, cursor, limit = 25 }) => {
    const page = Number(cursor ?? 1);
    const res = await sdk((ops) => ops.raw.tools.apps_list_apps({ query: { page, pageSize: limit, search: search || undefined } }));
    return {
      data: res.data.flatMap((c) => (c.connectionId ? [{ id: c.connectionId, label: c.name, hint: c.category ?? null, status: c.status ?? 'draft' }] : [])),
      nextCursor: res.pagination.hasNext ? String(page + 1) : null,
    };
  },
};
export const guardrailOptions: OptionSource = { key: 'guardrail-options', fetch: (p) => api.guardrails.options(p) };
/** Widgets, disabled with the reason when a button needs a tool outside `granted` (the draft's tools). */
export const widgetOptionsFor = (granted: string[]): OptionSource => ({ key: `widget-options:${[...granted].sort().join(',')}`, fetch: (p) => api.widgets.options(p, granted) });
/** Skills the agent may attach; `loading` keeps always-on or on-match ones. */
export const skillOptionsFor = (agentId: string, loading?: SkillLoading): OptionSource => ({ key: `skill-options:${agentId}:${loading ?? 'all'}`, fetch: (p) => api.skills.agents.options(agentId, p, loading) });

/** Pages of a source's options for a search, one page at a time as the list scrolls; the search runs on the server. */
export function useOptionSearch<P extends OptionsPage>(source: OptionSource<P>, search: string, enabled: boolean, limit = 25) {
  const [debounced, setDebounced] = React.useState(search);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 200);
    return () => clearTimeout(t);
  }, [search]);
  return useTeamInfiniteQuery({
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
  return useTeamQuery({
    queryKey: [source.key, 'labels', sorted],
    queryFn: () => source.fetch({ ids: sorted, limit: Math.max(sorted.length, 1) }),
    enabled: sorted.length > 0,
    staleTime: 60_000,
  });
}
