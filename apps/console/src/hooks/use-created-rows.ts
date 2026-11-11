'use client';

import * as React from 'react';

import { createdRowsReducer, type CreatedEntry, type FinishedWrite } from '@/lib/created-rows';

/** The rows a person created on a list page, for `DataTableWithViews`'s `created` prop. */
export interface CreatedRows<T> {
  /** Newest first. */
  rows: T[];
  /** Keep `row` in view at the top of the table, marked as new. */
  show: (row: T) => void;
  /** Let the rows follow the list's order and search again; the table calls it when the person pages, searches,
   *  filters or sorts. */
  clear: () => void;
  /** Stop pinning each created row a finished write names (a remove, revoke, archive, bulk delete or edit sent after
   *  the row was shown); the table calls it for every write the console finishes, with the id it keys rows by. */
  written: (write: FinishedWrite, idOf: (row: T) => string) => void;
}

/**
 * Hold the rows created on a list page, so the table shows each one right after it is added, whatever page, sort or
 * search the list is on (`withCreatedRows`), and lets it go once a later write changes or removes it. Pass the result
 * to the table as `created` and call `show` with the row the create returned.
 */
export function useCreatedRows<T>(): CreatedRows<T> {
  const [entries, dispatch] = React.useReducer(createdRowsReducer<T>, [] as CreatedEntry<T>[]);
  const rows = React.useMemo(() => entries.map((e) => e.row), [entries]);
  const show = React.useCallback((row: T) => dispatch({ type: 'show', row, at: Date.now() }), []);
  const clear = React.useCallback(() => dispatch({ type: 'clear' }), []);
  const written = React.useCallback((write: FinishedWrite, idOf: (row: T) => string) => dispatch({ type: 'written', write, idOf }), []);
  return React.useMemo(() => ({ rows, show, clear, written }), [rows, show, clear, written]);
}
