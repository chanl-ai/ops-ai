// A result table's columns as a person reads them, for any plugin: the record's name or title first, and id columns
// (Id, AccountId, account_id, or values that are 15- or 18-character record ids) hidden behind the table's View menu,
// where they stay for whoever needs one.

const NAME = /^(name|title|subject|label|display_?name|full_?name)$/i;
const ID_KEY = /^id$|[a-z0-9]Id$|_id$/;
const RECORD_ID = /^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$/;

/** Whether a column holds ids: by its key, or because every value in it is a record id. */
export function isIdColumn(key: string, rows: Record<string, unknown>[]): boolean {
  if (ID_KEY.test(key)) return true;
  const values = rows.map((r) => r[key]).filter((v) => v !== null && v !== undefined && v !== '');
  return values.length > 0 && values.every((v) => typeof v === 'string' && RECORD_ID.test(v));
}

/** The keys in reading order (the name or title first, ids last) and the id keys to start hidden. */
export function readingOrder(keys: string[], rows: Record<string, unknown>[]): { order: string[]; hidden: string[] } {
  const ids = keys.filter((k) => isIdColumn(k, rows));
  const rest = keys.filter((k) => !ids.includes(k));
  const name = rest.find((k) => NAME.test(k));
  const order = [...(name ? [name] : []), ...rest.filter((k) => k !== name), ...ids];
  // A table of ids alone keeps them showing: hiding every column would leave nothing to read.
  return { order, hidden: rest.length ? ids : [] };
}
