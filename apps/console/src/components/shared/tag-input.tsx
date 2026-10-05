'use client';

import * as React from 'react';
import { X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/** Comma or Enter adds a tag; Backspace on an empty input removes the last one. */
export function TagInput({
  value,
  onChange,
  placeholder = 'Add…',
  suggestions = [],
  disabled,
  className,
  id,
  format = (tag: string) => tag,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  disabled?: boolean;
  className?: string;
  id?: string;
  /** Display label for a stored tag, e.g. a tool id shown as words. */
  format?: (tag: string) => string;
}) {
  const [pending, setPending] = React.useState('');
  const add = (raw: string) => {
    const next = raw.split(',').map((s) => s.trim()).filter(Boolean);
    if (!next.length) return;
    onChange(Array.from(new Set([...value, ...next])));
    setPending('');
  };
  const remaining = suggestions.filter((tag) => !value.includes(tag) && `${tag} ${format(tag)}`.toLowerCase().includes(pending.toLowerCase()));
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div
        className={cn(
          'flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-transparent px-2 py-1 text-sm shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 dark:bg-input/30',
          disabled && 'opacity-50',
        )}
      >
        {value.map((tag) => (
          <Badge key={tag} variant="secondary" className="gap-1 pr-1 font-normal">
            {format(tag)}
            {!disabled && (
              <button type="button" onClick={() => onChange(value.filter((t) => t !== tag))} className="rounded-sm hover:bg-foreground/10" aria-label={`Remove ${format(tag)}`}>
                <X className="size-3" />
              </button>
            )}
          </Badge>
        ))}
        <input
          id={id}
          disabled={disabled}
          className="min-w-20 flex-1 bg-transparent py-0.5 outline-none placeholder:text-muted-foreground"
          value={pending}
          placeholder={value.length ? '' : placeholder}
          onChange={(e) => setPending(e.target.value)}
          onBlur={() => pending && add(pending)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault();
              add(pending);
            } else if (e.key === 'Backspace' && !pending && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
        />
      </div>
      {pending && remaining.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {remaining.slice(0, 6).map((s) => (
            <button key={s} type="button" onClick={() => add(s)} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent">
              {format(s)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
