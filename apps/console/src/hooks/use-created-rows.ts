'use client';

import * as React from 'react';

/** The rows a person created on a list page, for `DataTableWithViews`'s `created` prop. */
export interface CreatedRows<T> {
  /** Newest first. */
  rows: T[];
  /** Keep `row` in view at the top of the table, marked as new. */
  show: (row: T) => void;
  /** Let the rows follow the list's order and search again; the table calls it when the person pages, searches,
   *  filters or sorts. */
  clear: () => void;
}

/**
 * Hold the rows created on a list page, so the table shows each one right after it is added, whatever page, sort or
 * search the list is on (`withCreatedRows`). Pass the result to the table as `created` and call `show` with the row
 * the create returned.
 */
export function useCreatedRows<T>(): CreatedRows<T> {
  const [rows, setRows] = React.useState<T[]>([]);
  const show = React.useCallback((row: T) => setRows((prev) => [row, ...prev]), []);
  const clear = React.useCallback(() => setRows((prev) => (prev.length ? [] : prev)), []);
  return React.useMemo(() => ({ rows, show, clear }), [rows, show, clear]);
}
