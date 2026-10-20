'use client';

import { Plus, Trash2, Variable } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Toggle } from '@/components/ui/toggle';
import type { FilterCondition, FilterGroup, FilterOp } from '@/lib/types/knowledge-retrieval';

import { FILTER_OPS, isRuntime, RUNTIME_VARIABLES } from './retrieval-meta';

const placeholderFor = (op: FilterOp) => (op === 'one_of' ? 'e.g. ON, QC' : op === 'before' || op === 'after' ? 'e.g. 2026-01-01' : 'e.g. credit_card');

/**
 * Metadata conditions joined by all or any. A value is a literal or a runtime variable such as {case.product};
 * a variable carries a preview value that stands in outside a live run.
 */
export function FilterBuilder({ value, onChange, keys, idPrefix, disabled }: { value: FilterGroup; onChange: (v: FilterGroup) => void; keys: string[]; idPrefix: string; disabled?: boolean }) {
  const patch = (i: number, p: Partial<FilterCondition>) => onChange({ ...value, conditions: value.conditions.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  return (
    <div className="flex flex-col gap-2" data-testid={`${idPrefix}-filters`}>
      {value.conditions.length > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Match</span>
          <Select value={value.match} onValueChange={(m) => onChange({ ...value, match: m as FilterGroup['match'] })} disabled={disabled}>
            <SelectTrigger className="h-8 w-24 bg-background" aria-label="Match all or any">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">all</SelectItem>
              <SelectItem value="any">any</SelectItem>
            </SelectContent>
          </Select>
          <span className="text-muted-foreground">of these conditions</span>
        </div>
      )}
      {value.conditions.map((c, i) => {
        const runtime = isRuntime(c.value);
        return (
          <div key={c.id} className="flex flex-col gap-1.5 rounded-md border bg-background p-2">
            <div className="flex flex-wrap items-center gap-2">
              <Input list={`${idPrefix}-keys`} className="h-8 w-36 font-mono text-xs" value={c.key} placeholder="e.g. product" aria-label="Metadata key" disabled={disabled} onChange={(e) => patch(i, { key: e.target.value })} />
              <Select value={c.op} onValueChange={(op) => patch(i, { op: op as FilterOp })} disabled={disabled}>
                <SelectTrigger className="h-8 w-28" aria-label="Operator">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FILTER_OPS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {c.op !== 'exists' &&
                (runtime ? (
                  <Select value={c.value} onValueChange={(v) => patch(i, { value: v, preview: undefined })} disabled={disabled}>
                    <SelectTrigger className="h-8 min-w-40 flex-1 font-mono text-xs" aria-label="Runtime variable">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RUNTIME_VARIABLES.map((v) => (
                        <SelectItem key={v.name} value={v.name} className="font-mono text-xs">
                          {v.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input className="h-8 min-w-32 flex-1 font-mono text-xs" value={c.value} placeholder={placeholderFor(c.op)} aria-label="Value" disabled={disabled} onChange={(e) => patch(i, { value: e.target.value })} />
                ))}
              {c.op !== 'exists' && (
                <Toggle
                  size="sm"
                  pressed={runtime}
                  disabled={disabled}
                  aria-label="Use a runtime variable"
                  className="h-8"
                  onPressedChange={(on) => patch(i, on ? { value: RUNTIME_VARIABLES[0].name, preview: undefined } : { value: '', preview: undefined })}
                >
                  <Variable className="size-3.5" /> Variable
                </Toggle>
              )}
              {!disabled && (
                <Button variant="ghost" size="icon" className="size-8" onClick={() => onChange({ ...value, conditions: value.conditions.filter((_, j) => j !== i) })} aria-label="Remove condition">
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
            {runtime && c.op !== 'exists' && (
              <div className="flex flex-wrap items-center gap-2 pl-1 text-xs text-muted-foreground">
                <label htmlFor={`${idPrefix}-pv-${c.id}`}>Preview value</label>
                <Input id={`${idPrefix}-pv-${c.id}`} className="h-7 w-40 font-mono text-xs" value={c.preview ?? ''} placeholder={`e.g. ${RUNTIME_VARIABLES.find((x) => x.name === c.value)?.example ?? 'value'}`} disabled={disabled} onChange={(e) => patch(i, { preview: e.target.value })} />
                <span>Used when no run supplies {c.value}.</span>
              </div>
            )}
          </div>
        );
      })}
      <datalist id={`${idPrefix}-keys`}>
        {keys.map((k) => (
          <option key={k} value={k} />
        ))}
      </datalist>
      {!disabled && (
        <Button variant="outline" size="sm" className="h-7 w-fit" onClick={() => onChange({ ...value, conditions: [...value.conditions, { id: `f${Date.now()}`, key: '', op: 'is', value: '' }] })}>
          <Plus className="size-3.5" /> Add condition
        </Button>
      )}
    </div>
  );
}
