// Which renderers can draw each widget shape, and which one draws it. A renderer is named by id and takes one shape's
// data: the registry converts (rows to a series for a chart, a record to rows for a table) and never passes a tool
// name, so a new use case adds data, not a component. The id → component map lives with the renderers.
// Relative imports: the tests run under `node --test`, which does not resolve the `@/` alias.
import { recordToRows, rowsToSeries, seriesToRows } from '../../lib/widgets/convert.ts';
import type { ShapeData, WidgetHint, WidgetPart, WidgetShape } from '../../lib/types/widgets';

export type RendererId = 'table' | 'line' | 'bar' | 'area' | 'fields' | 'stat' | 'form' | 'confirmation' | 'task';

/** What each renderer draws: the shape its component takes as props. */
export interface RendererDraws {
  table: 'rows';
  line: 'series';
  bar: 'series';
  area: 'series';
  fields: 'record';
  stat: 'metric';
  form: 'form';
  confirmation: 'decision';
  task: 'steps';
}

/** The renderer chosen for a part and the data it takes, already converted. */
export type Resolved = { [R in RendererId]: { id: R; label: string; data: ShapeData[RendererDraws[R]] } }[RendererId];

type Option<S extends WidgetShape> = {
  [R in RendererId]: { id: R; label: string; from: (data: ShapeData[S], hint?: WidgetHint) => ShapeData[RendererDraws[R]] | null };
}[RendererId];

const same = <T>(d: T) => d;

/** Per shape, its renderers; the first is the default. */
const REGISTRY: { [S in WidgetShape]: Option<S>[] } = {
  rows: [
    { id: 'table', label: 'Table', from: same },
    { id: 'line', label: 'Line chart', from: (d, h) => rowsToSeries(d, h) },
    { id: 'bar', label: 'Bar chart', from: (d, h) => rowsToSeries(d, h) },
    { id: 'area', label: 'Area chart', from: (d, h) => rowsToSeries(d, h) },
  ],
  series: [
    { id: 'line', label: 'Line chart', from: same },
    { id: 'bar', label: 'Bar chart', from: same },
    { id: 'area', label: 'Area chart', from: same },
    { id: 'table', label: 'Table', from: (d, h) => seriesToRows(d, h?.x) },
  ],
  record: [
    { id: 'fields', label: 'Fields', from: same },
    { id: 'table', label: 'Table', from: recordToRows },
  ],
  metric: [{ id: 'stat', label: 'Metric', from: same }],
  form: [{ id: 'form', label: 'Form', from: same }],
  decision: [{ id: 'confirmation', label: 'Approval', from: same }],
  steps: [{ id: 'task', label: 'Steps', from: same }],
};

/** Every renderer that can draw this part, default first, each with its converted data. */
export function renderersFor(part: WidgetPart): Resolved[] {
  const options = REGISTRY[part.shape] as Option<typeof part.shape>[];
  return options.flatMap((o) => {
    const data = (o.from as (d: unknown, h?: WidgetHint) => unknown)(part.data, part.hint);
    return data === null ? [] : [{ id: o.id, label: o.label, data } as Resolved];
  });
}

/**
 * The renderer that draws this part: the person's choice on this widget when it can draw it, else the hint's
 * `prefer` when it can, else the shape's default.
 */
export function pickRenderer(part: WidgetPart, chosen?: string): Resolved {
  const options = renderersFor(part);
  return options.find((o) => o.id === chosen) ?? options.find((o) => o.id === part.hint?.prefer) ?? options[0];
}
