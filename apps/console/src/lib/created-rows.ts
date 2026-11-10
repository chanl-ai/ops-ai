/**
 * Rows a person has just created on a list page, kept in view above the page the server or the table returns: a list
 * sorted by name and paged, or narrowed by a search, would otherwise put the new row on another page or hide it, and
 * the person could not see that the add worked. Each row shows once: when the refetched page holds it too, the page's
 * copy is the one shown, in the pinned place.
 */

/**
 * Return the rows a table shows: the created rows first, in the order they were created (newest first), then the page
 * without them.
 *
 * @param page - the rows the list returned for the current page
 * @param created - the rows created on this page since the person last paged, searched, filtered or sorted, newest
 *   first; a row created twice (already listed) shows once, where its newest copy is
 * @param idOf - the row's stable id, the same one the table keys rows by
 * @returns the rows to give the table, and the ids to pin to its top
 */
export function withCreatedRows<T>(page: T[], created: T[], idOf: (row: T) => string): { rows: T[]; pinned: string[] } {
  if (!created.length) return { rows: page, pinned: [] };
  const onPage = new Map(page.map((r) => [idOf(r), r]));
  const pinned: string[] = [];
  const first: T[] = [];
  for (const row of created) {
    const id = idOf(row);
    if (pinned.includes(id)) continue;
    pinned.push(id);
    first.push(onPage.get(id) ?? row);
  }
  return { rows: [...first, ...page.filter((r) => !pinned.includes(idOf(r)))], pinned };
}

/** A created row and the time it was shown, so a write sent before then (the add itself) is not read as a change to it. */
export interface CreatedEntry<T> {
  row: T;
  shownAt: number;
}

/** A write the console finished: the values it was sent with and when it was sent (`Mutation.state`). */
export interface FinishedWrite {
  variables: unknown;
  submittedAt: number;
}

/** What `useCreatedRows` is asked to do: pin a row, let them all go, or take a finished write into account. */
export type CreatedRowsAction<T> =
  | { type: 'show'; row: T; at: number }
  | { type: 'clear' }
  | { type: 'written'; write: FinishedWrite; idOf: (row: T) => string };

/**
 * Return the created rows after `action`; the same array when nothing changed, so React keeps the render.
 *
 * @param state - the created rows, newest first
 * @param action - the change to apply
 * @returns the created rows to keep
 */
export function createdRowsReducer<T>(state: CreatedEntry<T>[], action: CreatedRowsAction<T>): CreatedEntry<T>[] {
  if (action.type === 'show') return [{ row: action.row, shownAt: action.at }, ...state];
  if (action.type === 'clear') return state.length ? [] : state;
  const { write, idOf } = action;
  const kept = state.filter((e) => !(write.submittedAt > e.shownAt && namesRow(write.variables, idOf(e.row))));
  return kept.length === state.length ? state : kept;
}

/**
 * Tell whether a write was sent for the row with `id`: its values are the id, a list holding it, or an object with a
 * top-level field that is the id or a list holding it. Removes, revokes, archives, bulk deletes and edits in the console
 * are all sent this way, so a write that names a created row means the pinned copy no longer matches the server.
 *
 * @param variables - the values the write was sent with
 * @param id - the created row's id, as the table keys it
 * @returns true when the write names the row
 */
export function namesRow(variables: unknown, id: string): boolean {
  const holds = (v: unknown) => v === id || (Array.isArray(v) && v.includes(id));
  if (holds(variables)) return true;
  return !!variables && typeof variables === 'object' && !Array.isArray(variables) && Object.values(variables).some(holds);
}
