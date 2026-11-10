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
