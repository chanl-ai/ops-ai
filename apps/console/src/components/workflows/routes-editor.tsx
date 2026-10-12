'use client';

import * as React from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import type { RouteFields, RouteWhen } from '@/lib/types/domain';

type FieldType = RouteFields['fields'][number]['type'];

/** The stored value shown as text: lists comma separated. */
const asText = (v: RouteWhen['value'] | undefined) => (v === undefined ? '' : Array.isArray(v) ? v.join(', ') : String(v));

/** Text typed for a route becomes the type the runtime compares: a number for number fields, a list for "one of". */
export function coerceRouteValue(text: string, type: FieldType | undefined, list: boolean): RouteWhen['value'] {
  const one = (t: string) => (type === 'number' && t.trim() !== '' && !Number.isNaN(Number(t)) ? Number(t) : t.trim());
  if (list) return text.split(',').map((t) => t.trim()).filter(Boolean).map(one) as (string | number)[];
  if (type === 'boolean') return text === 'true';
  return one(text);
}

/** Keeps the typed text while editing and commits on blur or Enter, so commas in a list survive typing. */
function ValueInput({ value, onCommit, label, placeholder }: { value: string; onCommit: (text: string) => void; label: string; placeholder: string }) {
  const [text, setText] = React.useState(value);
  React.useEffect(() => {
    setText(value);
  }, [value]);
  return (
    <Input
      aria-label={label}
      className="h-8 min-w-0"
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onCommit(text)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onCommit(text);
      }}
    />
  );
}

/**
 * One comparison per path out of a branch, plus the path taken when none matches. Publishing compiles these into a
 * route condition and refuses an unknown field or operator, a number comparison on text, or a missing default.
 */
export function RoutesEditor({
  branches,
  routes,
  defaultRoute,
  fields,
  onChange,
}: {
  branches: string[];
  routes: Record<string, RouteWhen>;
  defaultRoute?: string;
  fields?: RouteFields;
  onChange: (patch: { routes?: Record<string, RouteWhen>; defaultRoute?: string }) => void;
}) {
  if (!fields)
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  const typeOf = (field: string) => fields.fields.find((f) => f.name === field)?.type;
  const setRoute = (b: string, when: RouteWhen) => onChange({ routes: { ...routes, [b]: when } });

  return (
    <div className="flex flex-col gap-3" data-testid="routes-editor">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="route-default" className="text-xs">
          When nothing matches, go to
        </Label>
        <Select value={defaultRoute ?? ''} onValueChange={(v) => v && onChange({ defaultRoute: v })}>
          <SelectTrigger id="route-default" className="h-8 w-full" aria-label="Default route" aria-invalid={!defaultRoute}>
            <SelectValue placeholder="Choose the default path" />
          </SelectTrigger>
          <SelectContent>
            {branches.map((b) => (
              <SelectItem key={b} value={b}>
                {b}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {branches
        .filter((b) => b !== defaultRoute)
        .map((b) => {
          const when = routes[b];
          const type = when ? typeOf(when.field) : undefined;
          const ops = fields.ops.filter((o) => !type || o.types.includes(type));
          const op = fields.ops.find((o) => o.op === when?.op);
          return (
            <div key={b} className="flex flex-col gap-1.5 rounded-md border p-2.5" data-testid={`route-${b}`}>
              <span className="text-xs font-medium">Go to {b} when</span>
              <Select value={when?.field ?? ''} onValueChange={(f) => f && setRoute(b, { field: f, op: when?.op && fields.ops.find((o) => o.op === when.op)?.types.includes(typeOf(f)!) ? when.op : 'eq', value: when?.value ?? '' })}>
                <SelectTrigger className="h-8 w-full font-mono text-xs" aria-label={`${b} field`} aria-invalid={!when?.field}>
                  <SelectValue placeholder="Choose a field" />
                </SelectTrigger>
                <SelectContent>
                  {fields.fields.map((f) => (
                    <SelectItem key={f.name} value={f.name} className="font-mono text-xs">
                      {f.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-1.5">
                <Select value={when?.op ?? ''} onValueChange={(o) => o && when && setRoute(b, { ...when, op: o, value: coerceRouteValue(asText(when.value), type, !!fields.ops.find((x) => x.op === o)?.list) })} disabled={!when?.field}>
                  <SelectTrigger className="h-8 w-full" aria-label={`${b} operator`}>
                    <SelectValue placeholder="Operator" />
                  </SelectTrigger>
                  <SelectContent>
                    {ops.map((o) => (
                      <SelectItem key={o.op} value={o.op}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {type === 'boolean' ? (
                  <Select value={asText(when?.value)} onValueChange={(v) => v && when && setRoute(b, { ...when, value: v === 'true' })} disabled={!when?.field}>
                    <SelectTrigger className="h-8 w-full" aria-label={`${b} value`}>
                      <SelectValue placeholder="Value" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">true</SelectItem>
                      <SelectItem value="false">false</SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <ValueInput
                    label={`${b} value`}
                    value={asText(when?.value)}
                    placeholder={op?.list ? 'e.g. urgent, complaint' : type === 'number' ? 'e.g. 5000' : 'e.g. urgent'}
                    onCommit={(text) => when && setRoute(b, { ...when, value: coerceRouteValue(text, type, !!op?.list) })}
                  />
                )}
              </div>
            </div>
          );
        })}
    </div>
  );
}
