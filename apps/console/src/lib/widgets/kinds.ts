// Shaped tool results as widget kinds (c-176): agents-service shapes a tool's output as rows, a series, a record, a
// metric, a form, a decision or steps, the registry picks how to draw it, and this turns that choice into the kind the
// one renderer set draws. Relative imports: the tests run under `node --test`, which does not resolve the `@/` alias.
import type { ChartNode, Decision, FormSpec, KindNode, MetricNode, Steps, TableNode, WidgetHint } from '../types/widgets';
import { seriesToRows } from './convert.ts';
import type { Resolved } from '../../components/chat/widget-registry.ts';

export type DrawnNode = MetricNode | TableNode | ChartNode | KindNode;

const STEP: Record<Steps[number]['state'], 'pending' | 'active' | 'done' | 'failed'> = { pending: 'pending', running: 'active', done: 'done', failed: 'failed' };

function formKind(spec: FormSpec, title?: string): DrawnNode {
  const required = new Set(spec.schema.required ?? []);
  return {
    type: 'form',
    ...(title ? { title } : {}),
    fields: Object.entries(spec.schema.properties).map(([name, p]) => ({
      name,
      label: p.title ?? name,
      type: p.enum ? 'select' : p.type === 'boolean' ? 'boolean' : p.type === 'string' ? 'text' : 'number',
      ...(p.enum ? { options: p.enum.map(String) } : {}),
      ...(required.has(name) ? { required: true } : {}),
      ...(p.description ? { placeholder: p.description } : {}),
    })),
    submit: { label: 'Submit', reply: 'Submit' },
  };
}

function decisionKind(d: Decision): DrawnNode {
  return {
    type: 'confirm',
    title: d.summary,
    tone: 'warning',
    details: [{ label: 'Action', value: d.action }, ...Object.entries(d.args).map(([label, v]) => ({ label, value: typeof v === 'object' && v !== null ? JSON.stringify(v) : (v as string | number | boolean | null) }))],
    confirm: { label: 'Approve', reply: 'Approve' },
    cancel: { label: 'Reject', reply: 'Reject' },
  };
}

/** The kind that draws a registry choice; the hint's title names a record, a form and steps. */
export function toKind(resolved: Resolved, hint?: WidgetHint): DrawnNode {
  switch (resolved.id) {
    case 'table':
      return { type: 'table', rows: resolved.data };
    case 'line':
    case 'bar':
    case 'area': {
      const x = hint?.x ?? 'x';
      return { type: 'chart', rows: seriesToRows(resolved.data, x), x, y: resolved.data.series.map((s) => s.name), kind: resolved.id };
    }
    case 'fields':
      return { type: 'entity', title: hint?.title ?? 'Details', fields: Object.entries(resolved.data).map(([label, value]) => ({ label, value })) };
    case 'stat':
      return { type: 'metric', ...resolved.data };
    case 'form':
      return formKind(resolved.data, hint?.title);
    case 'confirmation':
      return decisionKind(resolved.data);
    case 'task':
      return { type: 'tracker', title: hint?.title ?? 'Steps', steps: resolved.data.map((s) => ({ label: s.title, state: STEP[s.state] })) };
  }
}
