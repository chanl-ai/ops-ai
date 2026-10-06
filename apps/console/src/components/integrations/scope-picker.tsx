'use client';

import { Checkbox } from '@/components/ui/checkbox';
import type { ScopeDef } from '@/lib/types/integrations';
import { cn } from '@/lib/utils';

/** Scopes grouped by area, each with what granting it allows. `locked` scopes show as already granted. */
export function ScopePicker({ scopes, selected, onChange, locked = [] }: { scopes: ScopeDef[]; selected: string[]; onChange: (ids: string[]) => void; locked?: string[] }) {
  const groups = [...new Set(scopes.map((s) => s.group))];
  const toggle = (sid: string, on: boolean) => onChange(on ? [...selected, sid] : selected.filter((x) => x !== sid));
  return (
    <div className="flex flex-col gap-3" data-testid="scope-picker">
      <p className="text-xs text-muted-foreground tabular-nums">
        {selected.length + locked.length} of {scopes.length} selected
      </p>
      {groups.map((g) => (
        <fieldset key={g} className="flex flex-col gap-1.5">
          <legend className="pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{g}</legend>
          <div className="divide-y rounded-md border">
            {scopes
              .filter((s) => s.group === g)
              .map((s) => {
                const isLocked = locked.includes(s.id);
                const on = isLocked || selected.includes(s.id);
                return (
                  <label key={s.id} htmlFor={`scope-${s.id}`} className={cn('flex items-start gap-3 px-3 py-2.5', isLocked ? 'cursor-default bg-muted/40' : 'cursor-pointer')}>
                    <Checkbox id={`scope-${s.id}`} checked={on} disabled={isLocked} onCheckedChange={(c) => toggle(s.id, c === true)} className="mt-0.5" />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                        {s.label}
                        <span className={cn('rounded border px-1.5 text-[11px] font-normal', s.access === 'write' ? 'border-amber-500/30 text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>{s.access === 'write' ? 'Write' : 'Read'}</span>
                        {isLocked && <span className="text-xs font-normal text-muted-foreground">Granted</span>}
                      </span>
                      <span className="block text-xs text-muted-foreground">{s.description}</span>
                      <code className="font-mono text-[11px] text-muted-foreground">{s.id}</code>
                    </span>
                  </label>
                );
              })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
