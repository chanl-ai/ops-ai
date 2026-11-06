/** The column id `idColumn` gives the record id, and the trailing row-actions column. */
const ID = 'recordId';
const ACTIONS = 'actions';

/**
 * Column ids with the record id after every data column and before the row actions, so every list reads the same
 * way for every person: what the row is first, its id last, whatever columns a role sees.
 */
export function idLast(ids: string[]): string[] {
  if (!ids.includes(ID)) return ids;
  const rest = ids.filter((id) => id !== ID && id !== ACTIONS);
  return [...rest, ID, ...(ids.includes(ACTIONS) ? [ACTIONS] : [])];
}
