'use client';

import { Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/** An ordered list of short lines (goals, steps, rules). Empty rows are dropped by the generator. */
export function ListField({ id, value, onChange, placeholder, addLabel, numbered, invalid }: { id: string; value: string[]; onChange: (v: string[]) => void; placeholder: string; addLabel: string; numbered?: boolean; invalid?: boolean }) {
  const rows = value.length ? value : [''];
  const put = (i: number, v: string) => onChange(rows.map((x, j) => (j === i ? v : x)));
  return (
    <div className="flex flex-col gap-1.5">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-1.5">
          {numbered && <span className="w-5 shrink-0 text-right text-xs text-muted-foreground tabular-nums">{i + 1}.</span>}
          <Input
            id={i === 0 ? id : `${id}-${i}`}
            value={row}
            onChange={(e) => put(i, e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onChange([...rows.slice(0, i + 1), '', ...rows.slice(i + 1)]);
              }
            }}
            placeholder={i === 0 ? placeholder : undefined}
            aria-invalid={invalid && i === 0}
            aria-label={`${addLabel.replace(/^Add /, '')} ${i + 1}`}
          />
          <Button type="button" variant="ghost" size="icon" className="size-8 shrink-0" aria-label={`Remove line ${i + 1}`} disabled={rows.length === 1 && !row} onClick={() => onChange(rows.length === 1 ? [''] : rows.filter((_, j) => j !== i))}>
            <X className="size-3.5" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="ghost" size="sm" className="self-start" onClick={() => onChange([...rows, ''])}>
        <Plus className="size-3.5" /> {addLabel}
      </Button>
    </div>
  );
}
