'use client';

import { Plus, Sparkles, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { MetadataMapping } from '@/lib/types/knowledge';

type Mode = 'field' | 'static' | 'ai';
const MODE_LABEL: Record<Mode, string> = { field: 'From a source field', static: 'Fixed value', ai: 'Extract with AI' };
const PLACEHOLDER: Record<Mode, string> = { field: 'e.g. Dept', static: 'e.g. en', ai: 'e.g. product' };

const split = (from: string): [Mode, string] => {
  const m = from.match(/^(field|static|ai):(.*)$/);
  return m ? [m[1] as Mode, m[2]] : ['static', from];
};

/** Metadata keys and where each value comes from: a field at the source, a fixed value, or a model reading the document at ingest. */
export function MetadataMappingEditor({ value, onChange, model, required = [], disabled }: { value: MetadataMapping[]; onChange: (v: MetadataMapping[]) => void; model: string; required?: string[]; disabled?: boolean }) {
  const patch = (i: number, p: MetadataMapping) => onChange(value.map((x, j) => (j === i ? p : x)));
  const missing = required.filter((r) => !value.some((m) => m.key === r));
  return (
    <div className="flex flex-col gap-2">
      {value.length === 0 && <p className="text-sm text-muted-foreground">No metadata mapped. Items carry only their title, owner, version and dates.</p>}
      {value.map((m, i) => {
        const [mode, v] = split(m.from);
        return (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Input className="h-8 w-36 bg-background font-mono text-xs" value={m.key} placeholder="e.g. product" aria-label="Metadata key" disabled={disabled} onChange={(e) => patch(i, { ...m, key: e.target.value })} />
            <span className="text-muted-foreground">←</span>
            <Select value={mode} onValueChange={(x) => patch(i, { ...m, from: `${x}:${x === 'ai' && !v ? m.key : v}` })} disabled={disabled}>
              <SelectTrigger className="h-8 w-44 bg-background" aria-label="Where the value comes from">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(MODE_LABEL) as Mode[]).map((k) => (
                  <SelectItem key={k} value={k}>
                    {MODE_LABEL[k]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              className="h-8 min-w-32 flex-1 bg-background font-mono text-xs"
              value={v}
              placeholder={PLACEHOLDER[mode]}
              aria-label={mode === 'ai' ? 'Field the model extracts' : mode === 'field' ? 'Source field' : 'Value'}
              disabled={disabled}
              onChange={(e) => patch(i, { ...m, from: `${mode}:${e.target.value}` })}
            />
            {mode === 'ai' && (
              <Badge variant="outline" className="gap-1 font-normal">
                <Sparkles className="size-3" /> Model call at ingest · {model}
              </Badge>
            )}
            {!disabled && (
              <Button variant="ghost" size="icon" className="size-8" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label={`Remove ${m.key || 'mapping'}`}>
                <Trash2 className="size-3.5" />
              </Button>
            )}
          </div>
        );
      })}
      {missing.length > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Required by a knowledge base that reads this source and not mapped here: {missing.join(', ')}. Items without them are held.
        </p>
      )}
      {!disabled && (
        <Button variant="outline" size="sm" className="w-fit" onClick={() => onChange([...value, { key: '', from: 'static:' }])}>
          <Plus className="size-3.5" /> Add mapping
        </Button>
      )}
    </div>
  );
}
