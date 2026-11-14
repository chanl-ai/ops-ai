'use client';

import { Fragment, type ReactNode } from 'react';
import { ChevronDown, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
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
  variant = 'outline',
  align = 'start',
}: {
  label: string;
  /** Names the trigger when several menus share a page (the block menu of each container). */
  ariaLabel?: string;
  /**
   * Each choice; `description` adds a second line, `icon` a leading icon, and `group` a heading over the run of items
   * that share it (a separator between groups).
   */
  items: { value: string; label: ReactNode; description?: ReactNode; icon?: ReactNode; group?: string; testId?: string }[];
  onSelect: (value: string) => void;
  disabled?: boolean;
  className?: string;
  testId?: string;
  /** `primary` for the page's main action. */
  variant?: 'outline' | 'primary';
  align?: 'start' | 'end';
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant={variant === 'primary' ? 'default' : 'outline'} size="sm" className={cn('justify-between', className)} disabled={disabled} aria-label={ariaLabel} data-testid={testId}>
          <span className="inline-flex items-center gap-1.5">
            <Plus className="size-3.5" /> {label}
          </span>
          <ChevronDown className={cn('size-3.5', variant === 'primary' ? 'opacity-80' : 'text-muted-foreground')} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className={cn('min-w-56', items.some((i) => i.description) && 'w-72')}>
        {items.map((i, n) => {
          const starts = n === 0 || items[n - 1].group !== i.group;
          return (
            <Fragment key={i.value}>
              {starts && n > 0 && <DropdownMenuSeparator />}
              {starts && i.group && <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">{i.group}</DropdownMenuLabel>}
              <DropdownMenuItem onSelect={() => onSelect(i.value)} className={cn(i.description && 'items-start')} data-testid={i.testId}>
                {i.icon && <span className={cn('shrink-0 text-muted-foreground [&_svg]:size-4', i.description && 'mt-0.5')}>{i.icon}</span>}
                {i.description ? (
                  <span className="flex min-w-0 flex-col">
                    <span>{i.label}</span>
                    <span className="text-xs text-muted-foreground">{i.description}</span>
                  </span>
                ) : (
                  i.label
                )}
              </DropdownMenuItem>
            </Fragment>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
