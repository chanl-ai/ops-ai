// Pure conversions between widget shapes, so one result can be drawn as a chart or a table. Relative type import:
// the tests run under `node --test`, which does not resolve the `@/` alias.
import type { Cell, RecordData, Rows, Series, WidgetHint } from '../types/widgets';

const isNumber = (v: Cell): v is number => typeof v === 'number' && Number.isFinite(v);
const isLabel = (v: Cell) => typeof v === 'string' || isNumber(v);

/**
 * Rows as a series: one label key for x (the hint's, else the first key holding text on every row) and the numeric
 * keys as series (the hint's that are numeric, else every other all-numeric key). Null when the rows have no such
 * pair, so a caller offers the chart only when it can be drawn.
 */
export function rowsToSeries(rows: Rows, hint?: Pick<WidgetHint, 'x' | 'y'>): Series | null {
  if (!rows.length) return null;
  const keys = Object.keys(rows[0]);
  const numeric = keys.filter((k) => rows.every((r) => isNumber(r[k])));
  const x = hint?.x && keys.includes(hint.x) && rows.every((r) => isLabel(r[hint.x!])) ? hint.x : keys.find((k) => rows.every((r) => typeof r[k] === 'string'));
  if (!x) return null;
  const wanted = hint?.y?.filter((k) => k !== x && numeric.includes(k));
  const y = wanted?.length ? wanted : numeric.filter((k) => k !== x);
  if (!y.length) return null;
  return { x: rows.map((r) => r[x] as string | number), series: y.map((name) => ({ name, y: rows.map((r) => r[name] as number) })) };
}

/** A series as rows: one row per x value, the x under `xKey` and each series under its name. */
export function seriesToRows(s: Series, xKey = 'x'): Rows {
  return s.x.map((x, i) => Object.fromEntries([[xKey, x], ...s.series.map((line) => [line.name, line.y[i] ?? null])]));
}

/** A record as two-column rows, field and value, in the record's order. */
export function recordToRows(r: RecordData): Rows {
  return Object.entries(r).map(([field, value]) => ({ Field: field, Value: value }));
}
