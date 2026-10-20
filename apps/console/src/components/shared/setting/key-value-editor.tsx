'use client';

import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export interface KeyValue {
  key: string;
  value: string;
}

/** Rows of name and value for headers and variables. Values may be masked when they are secrets. */
export function KeyValueEditor({ value, onChange, keyPlaceholder = 'e.g. X-Region', valuePlaceholder = 'e.g. eu-west', maskValues, label }: { value: KeyValue[]; onChange: (v: KeyValue[]) => void; keyPlaceholder?: string; valuePlaceholder?: string; maskValues?: boolean; label: string }) {
  const set = (i: number, patch: Partial<KeyValue>) => onChange(value.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="flex flex-col gap-2" role="group" aria-label={label}>
      {value.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input value={r.key} onChange={(e) => set(i, { key: e.target.value })} placeholder={keyPlaceholder} aria-label={`${label} name ${i + 1}`} className="bg-card font-mono text-xs" />
          <Input value={r.value} type={maskValues ? 'password' : 'text'} onChange={(e) => set(i, { value: e.target.value })} placeholder={valuePlaceholder} aria-label={`${label} value ${i + 1}`} className="bg-card font-mono text-xs" />
          <Button type="button" variant="ghost" size="icon" className="size-8 shrink-0" aria-label={`Remove ${r.key || 'row'}`} onClick={() => onChange(value.filter((_, j) => j !== i))}>
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => onChange([...value, { key: '', value: '' }])}>
        <Plus className="size-3.5" /> Add
      </Button>
    </div>
  );
}
