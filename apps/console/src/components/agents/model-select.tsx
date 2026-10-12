'use client';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ModelAlias } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

/**
 * models-service charges by its price table and logs an alias priced at zero as costing nothing, so an agent on one
 * shows no spend however much it runs. Prices absent (no models-service behind the agents service) are unknown, not zero.
 */
export const isUnpriced = (a: ModelAlias | undefined) => !!a && a.inputPerMillion !== undefined && a.outputPerMillion !== undefined && Number(a.inputPerMillion) === 0 && Number(a.outputPerMillion) === 0;

/** The FormField hint for the chosen alias: the no-price warning when it applies, else `fallback`. */
export function modelHint(aliases: ModelAlias[], value: string, fallback?: React.ReactNode): React.ReactNode {
  return isUnpriced(aliases.find((a) => a.name === value)) ? (
    <span className="text-warning-text" data-testid="model-no-price">
      No price is set for {value}, so its spend reports as zero. An admin can price it in Models.
    </span>
  ) : (
    fallback
  );
}

/**
 * The aliases publish accepts. An agent saved on an alias no longer offered still shows it, marked, so it can be
 * changed; an unpriced alias is marked in the list.
 */
export function ModelSelect({ id, value, onValueChange, aliases, className, invalid }: { id: string; value: string; onValueChange: (v: string) => void; aliases: ModelAlias[]; className?: string; invalid?: boolean }) {
  const offered = aliases.some((a) => a.name === value);
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger id={id} className={cn('w-full font-mono text-xs', className)} aria-invalid={invalid}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {value && !offered && (
          <SelectItem value={value} className="font-mono text-xs">
            {value} (publish refuses this alias)
          </SelectItem>
        )}
        {aliases.map((a) => (
          <SelectItem key={a.name} value={a.name} className="font-mono text-xs">
            {a.name}
            {isUnpriced(a) && <span className="font-sans text-muted-foreground"> · no price</span>}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
