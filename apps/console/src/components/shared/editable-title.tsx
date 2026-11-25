'use client';

import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * A record's name edited where it is shown, in PageLayout's title slot. It reads as the title until it is focused, and
 * `error` says why the name cannot be saved yet.
 */
export function EditableTitle({ value, onChange, label, error, disabled }: { value: string; onChange: (next: string) => void; label: string; error?: string; disabled?: boolean }) {
  return (
    <div className="min-w-0">
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-label={label}
        aria-invalid={!!error}
        data-testid="page-title-input"
        className={cn('-ml-[5px] h-auto w-[calc(100%+5px)] min-w-0 truncate rounded-md border-transparent bg-transparent px-1 py-0 text-xl font-semibold shadow-none hover:border-input focus-visible:border-ring disabled:opacity-100 sm:text-2xl md:text-2xl', error && 'border-destructive')}
      />
      {error && <p className="text-xs text-destructive-text">{error}</p>}
    </div>
  );
}
