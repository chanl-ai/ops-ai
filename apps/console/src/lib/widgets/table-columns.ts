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

// A result's columns and values as a person reads them, whichever tool or plugin answered: keys in words, dates in the
// console's date format, and columns with nothing in any row left out.

const ACRONYMS = new Set(['id', 'url', 'api', 'sla', 'kb', 'ip', 'pdf', 'csv']);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;

/** A key in words: `knowledgeBase` and `knowledge_base` read "Knowledge base", `CaseNumber` "Case number". */
export function columnLabel(key: string): string {
  const words = key
    .replace(/[_.-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w.toLowerCase()));
  if (!words.length) return key;
  const [first, ...rest] = words;
  return [first === first.toUpperCase() ? first : first[0].toUpperCase() + first.slice(1), ...rest].join(' ');
}

/** The label a column shows: the one the result gave, unless that is its key as written. */
export const shownLabel = (key: string, label?: string) => (label && label !== key ? label : columnLabel(key));

const blank = (v: unknown) => v === null || v === undefined || (typeof v === 'string' && /^\s*(—|-)?\s*$/.test(v)) || (Array.isArray(v) && v.length === 0);

/** Whether no row has anything in the column, so it only takes room. */
export const isEmptyColumn = (key: string, rows: Record<string, unknown>[]) => rows.length > 0 && rows.every((r) => blank(r[key]));

/** Whether a value is a date or a date and time as an API writes it. */
export const isIsoDate = (v: unknown): v is string => typeof v === 'string' && (ISO_DATE.test(v) || ISO_DATE_TIME.test(v));

/** A date as the console writes dates elsewhere: "1 Oct 2026", with the time when the value has one. */
export function dateCell(v: string): string {
  const at = ISO_DATE.test(v) ? new Date(`${v}T12:00:00`) : new Date(v.replace(' ', 'T'));
  if (Number.isNaN(at.getTime())) return v;
  const day: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' };
  return ISO_DATE.test(v) ? at.toLocaleDateString('en-CA', day) : at.toLocaleString('en-CA', { ...day, hour: '2-digit', minute: '2-digit', hour12: false });
}
