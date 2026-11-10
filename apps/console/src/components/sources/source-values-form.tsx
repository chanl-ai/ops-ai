'use client';

import { Plus, Trash2 } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { ScopePicker } from '@/components/sources/scope-picker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { SourceInputField } from '@/lib/types/knowledge';

/** Labels and hints for a website source's settings; any other input shows its own name and description. */
const KNOWN: Record<string, { label: string; hint?: string; placeholder?: string }> = {
  start: { label: 'Start', hint: 'A page, a list of pages, or a sitemap. A site’s sitemap is also found from robots.txt.', placeholder: 'e.g. https://help.example.com/sitemap.xml' },
  follow_links: { label: 'Follow links', hint: 'Same site only.' },
  depth: { label: 'Depth', hint: 'How many links deep to follow from the start.' },
  max_pages: { label: 'Max pages' },
  include: { label: 'Include', hint: 'Patterns match the page path.', placeholder: 'e.g. /claims/**' },
  exclude: { label: 'Exclude', hint: 'Exclude wins. Patterns match the page path.', placeholder: 'e.g. /claims/archive/**' },
  rate: { label: 'Speed', hint: 'Pages per second for this site. robots.txt can only make it slower.' },
  render: { label: 'Render JavaScript', hint: 'Loads pages in a browser first. 5 to 10 times slower.' },
};
const PATTERNS = new Set(['include', 'exclude']);

const label = (name: string) => KNOWN[name]?.label ?? name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

/** A start address is a full https address; a rule pattern starts with `/`. Keyed by input name. */
export function valueErrors(inputs: Record<string, SourceInputField>, values: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, field] of Object.entries(inputs)) {
    const v = values[name];
    const empty = v === undefined || v === null || v === '' || (Array.isArray(v) && v.every((x) => !String(x).trim()));
    if (empty) {
      if (field.required !== false) out[name] = `Enter ${label(name).toLowerCase()}.`;
      continue;
    }
    if (name === 'start') {
      const list = Array.isArray(v) ? v.map(String) : [String(v)];
      if (list.filter((x) => x.trim()).some((x) => !/^https:\/\/[^\s/]+\.[^\s]+$/.test(x.trim())))
        out[name] = 'Enter a full address that starts with https://, such as https://help.example.com/sitemap.xml.';
    }
    if (PATTERNS.has(name) && Array.isArray(v) && v.some((x) => String(x).trim() && !String(x).trim().startsWith('/')))
      out[name] = 'A pattern starts with /, for example /claims/**.';
  }
  return out;
}

/** The value an input starts with: what was saved, else the plugin's default, else empty for its type. */
export function initialValues(inputs: Record<string, SourceInputField>, saved: Record<string, unknown> = {}): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(inputs).map(([name, f]) => [name, saved[name] ?? f.default ?? (f.type === 'array' ? [] : f.type === 'boolean' ? false : f.type === 'integer' || f.type === 'number' ? undefined : '')]),
  );
}

/**
 * A website's or an app source's own settings, drawn from the inputs its plugin declares: text, numbers, switches,
 * choices and lists of patterns. `only` limits it to some inputs (a source's Settings shows its rules and pace).
 */
export function SourceValuesForm({
  idPrefix,
  inputs,
  values,
  onChange,
  errors = {},
  only,
  disabled,
  scopeSource,
}: {
  idPrefix: string;
  inputs: Record<string, SourceInputField>;
  values: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  errors?: Record<string, string>;
  only?: string[];
  disabled?: boolean;
  /** The plugin source whose scopes tool fills inputs that declare a `picker`; without it they are typed. */
  scopeSource?: { plugin: string; source: string };
}) {
  const set = (name: string, v: unknown) => onChange({ ...values, [name]: v });
  const names = Object.keys(inputs).filter((n) => !only || only.includes(n));
  return (
    <div className="flex flex-col gap-4">
      {names.map((name) => {
        const f = inputs[name];
        const id = `${idPrefix}-${name}`;
        const v = values[name];
        const meta = KNOWN[name];
        const hint = meta?.hint ?? f.description;
        const error = errors[name];
        if (f.type === 'boolean')
          return (
            <div key={name} className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <label htmlFor={id} className="text-sm font-medium">
                  {label(name)}
                </label>
                {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
              </div>
              <Switch id={id} checked={!!v} disabled={disabled} onCheckedChange={(x) => set(name, x)} />
            </div>
          );
        if (f.type === 'array' && f.picker && scopeSource) {
          // What the other pickers hold so far are the parents this one lists the contents of (a site's libraries).
          const parents = names.filter((n) => n !== name && inputs[n].picker).flatMap((n) => (Array.isArray(values[n]) ? (values[n] as unknown[]).map(String) : []));
          return (
            <FormField key={name} id={id} label={label(name)} hint={hint} error={error} optional={f.required === false}>
              <ScopePicker id={id} plugin={scopeSource.plugin} source={scopeSource.source} kind={f.picker} parents={parents} value={Array.isArray(v) ? v.map(String) : []} onChange={(x) => set(name, x)} disabled={disabled} />
            </FormField>
          );
        }
        if (f.type === 'array') {
          const list = Array.isArray(v) ? v.map(String) : [];
          return (
            <FormField key={name} id={id} label={label(name)} hint={hint} error={error} optional={f.required === false}>
              <div className="flex flex-col gap-2">
                {list.map((x, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      id={i === 0 ? id : undefined}
                      className="bg-background font-mono text-xs"
                      value={x}
                      placeholder={meta?.placeholder ?? 'e.g. /help/**'}
                      aria-label={`${label(name)} ${i + 1}`}
                      aria-invalid={!!error}
                      disabled={disabled}
                      onChange={(e) => set(name, list.map((y, j) => (j === i ? e.target.value : y)))}
                    />
                    <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label={`Remove ${label(name).toLowerCase()} ${i + 1}`} disabled={disabled} onClick={() => set(name, list.filter((_, j) => j !== i))}>
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
                <Button variant="outline" size="sm" className="w-fit" disabled={disabled} onClick={() => set(name, [...list, PATTERNS.has(name) ? '/' : ''])}>
                  <Plus className="size-3.5" /> {PATTERNS.has(name) ? 'Add rule' : `Add ${label(name).toLowerCase()}`}
                </Button>
              </div>
            </FormField>
          );
        }
        if (f.enum?.length)
          return (
            <FormField key={name} id={id} label={label(name)} hint={hint} error={error} optional={f.required === false}>
              <Select value={v === undefined ? undefined : String(v)} onValueChange={(x) => set(name, f.type === 'integer' || f.type === 'number' ? Number(x) : x)} disabled={disabled}>
                <SelectTrigger id={id} className="w-full bg-background" aria-invalid={!!error}>
                  <SelectValue placeholder="Choose" />
                </SelectTrigger>
                <SelectContent>
                  {f.enum.map((o) => (
                    <SelectItem key={String(o)} value={String(o)}>
                      {String(o)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          );
        const numeric = f.type === 'integer' || f.type === 'number';
        return (
          <FormField key={name} id={id} label={label(name)} hint={hint} error={error} optional={f.required === false}>
            <Input
              id={id}
              type={numeric ? 'number' : 'text'}
              step={f.type === 'number' ? 'any' : undefined}
              className={numeric ? 'w-32 bg-background tabular-nums' : 'bg-background'}
              value={v === undefined || v === null ? '' : String(v)}
              placeholder={meta?.placeholder}
              aria-invalid={!!error}
              disabled={disabled}
              onChange={(e) => set(name, numeric ? (e.target.value === '' ? undefined : Number(e.target.value)) : e.target.value)}
            />
          </FormField>
        );
      })}
    </div>
  );
}
