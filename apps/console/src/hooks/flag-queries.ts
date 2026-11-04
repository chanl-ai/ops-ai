'use client';

import * as React from 'react';

import type { FlagName } from '@/lib/types/flags';

import { useMe } from './me-queries';

export type FlagState = 'loading' | 'on' | 'off';

/**
 * Whether the install turns a flag on, from platform-service's /v1/me. Off platform sign-in there is no /v1/me,
 * so every flag is off; a failed read is off too, the safe side for a feature not yet released.
 */
export function useFlagState(name: FlagName): FlagState {
  const me = useMe();
  if (!me.isEnabled || me.isError) return 'off';
  if (me.isPending) return 'loading';
  return me.data.flags?.find((f) => f.name === name)?.on ? 'on' : 'off';
}

/** On only once the answer says so, so a flagged entry never shows while the answer loads. */
export const useFlag = (name: FlagName) => useFlagState(name) === 'on';

/** The items whose flag is on; an item with no `flag` always stays. For lists of pages, actions, kinds and options. */
export function useFlagged<T extends { flag?: FlagName }>(items: readonly T[]): T[] {
  const me = useMe();
  // Joined to a string so the list keeps its identity across renders until a flag changes, for memoised columns.
  const on = (me.data?.flags ?? []).filter((f) => f.on).map((f) => f.name).join(',');
  return React.useMemo(() => items.filter((i) => !i.flag || on.split(',').includes(i.flag)), [items, on]);
}
