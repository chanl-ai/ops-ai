'use client';

import type { ReactNode } from 'react';
import { ChevronDown, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

/**
 * A button that opens a menu of things to add, one choice per click. A `Select` keeps its choice as its value, so
 * used as a menu it needs `value=""` and reads as a field with nothing chosen; this reads as the action it is.
 */
export function AddMenu({
  label,
  ariaLabel,
  items,
  onSelect,
  disabled,
  className,
  testId,
}: {
  label: string;
  /** Names the trigger when several menus share a page (the block menu of each container). */
  ariaLabel?: string;
  items: { value: string; label: ReactNode }[];
  onSelect: (value: string) => void;
  disabled?: boolean;
  className?: string;
  testId?: string;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" className={cn('justify-between', className)} disabled={disabled} aria-label={ariaLabel} data-testid={testId}>
          <span className="inline-flex items-center gap-1.5">
            <Plus className="size-3.5" /> {label}
          </span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        {items.map((i) => (
          <DropdownMenuItem key={i.value} onSelect={() => onSelect(i.value)}>
            {i.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
