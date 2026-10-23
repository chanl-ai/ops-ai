'use client';

import * as React from 'react';
import {
  type DefaultError,
  type InfiniteData,
  type QueryKey,
  type UseInfiniteQueryOptions,
  type UseQueryOptions,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query';

import { queriesNeedTeam } from '@/lib/api';
import { currentTeamId, teamStore } from '@/lib/api/team-context';

import { useTeamReady } from './use-team';

/**
 * The one way the console reads through React Query (c-505). A team's data waits until the person's teams are known
 * and the team it would be asked for is one of them, and its key ends with that team, so no request leaves for a team
 * the person does not hold and one team's answer is never shown in another. `scripts/check-standards.mjs` refuses the
 * React Query read hooks anywhere else.
 */

/** What the embedded chat's keys end with in place of a team. */
const WIDGET = 'widget';

/** `key` as the wrapper caches it for a team (the current one by default): for reading or writing the cache directly. */
export function teamKey<K extends QueryKey>(key: K, team: string = queriesNeedTeam ? currentTeamId() : WIDGET): readonly [...K, { team: string }] {
  return [...key, { team }] as const;
}

function useTeamScope(enabled: boolean | undefined): { team: string; enabled: boolean } {
  const ready = useTeamReady();
  const team = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  return { team, enabled: ready && (enabled ?? true) };
}
/** The embedded chat (apps/embed) reuses the chat hooks with a widget session and no team: nothing to wait for. */
const useWidgetScope = (enabled: boolean | undefined) => ({ team: WIDGET, enabled: enabled ?? true });
const useScope = queriesNeedTeam ? useTeamScope : useWidgetScope;

/** useQuery for data a team owns: enabled once the team is resolved and the caller's own `enabled` holds, keyed by the team. */
export function useTeamQuery<TQueryFnData = unknown, TError = DefaultError, TData = TQueryFnData, TQueryKey extends QueryKey = QueryKey>(
  options: UseQueryOptions<TQueryFnData, TError, TData, TQueryKey> & { enabled?: boolean },
) {
  const scope = useScope(options.enabled);
  return useQuery({ ...options, queryKey: teamKey(options.queryKey, scope.team) as unknown as TQueryKey, enabled: scope.enabled });
}

/** useInfiniteQuery with the same readiness and team key as useTeamQuery. */
export function useTeamInfiniteQuery<TQueryFnData, TError = DefaultError, TData = InfiniteData<TQueryFnData>, TQueryKey extends QueryKey = QueryKey, TPageParam = unknown>(
  options: UseInfiniteQueryOptions<TQueryFnData, TError, TData, TQueryKey, TPageParam> & { enabled?: boolean },
) {
  const scope = useScope(options.enabled);
  return useInfiniteQuery({ ...options, queryKey: teamKey(options.queryKey, scope.team) as unknown as TQueryKey, enabled: scope.enabled });
}

/**
 * useQuery for what no team decides and the gate itself needs before a team is chosen: the person's teams, who they
 * are, and the sign-in policy and options. It does not wait for the team, since the team is chosen from it.
 */
export function useSessionQuery<TQueryFnData = unknown, TError = DefaultError, TData = TQueryFnData, TQueryKey extends QueryKey = QueryKey>(
  options: UseQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
) {
  return useQuery(options);
}
