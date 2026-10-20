'use client';

import type { ReactNode } from 'react';
import { Lock } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

/**
 * One setting in a list: its label, a one-line effect, the default and the role that may change it. A person without
 * the role sees the value and a lock with the role's name. One component draws all four so a page cannot leave one out.
 */
export function SettingRow({
  id,
  label,
  effect,
  defaultLabel,
  role,
  canChange = true,
  children,
  className,
}: {
  id?: string;
  label: ReactNode;
  /** What changes when the value does, in one line. */
  effect: ReactNode;
  /** The default, as a person reads it: "On", "Major changes only". */
  defaultLabel: string;
  /** The role that may change it. */
  role: string;
  canChange?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-x-6 gap-y-2 py-3', className)} data-testid={id ? `setting-row-${id}` : undefined}>
      <div className="min-w-0 flex-1 basis-64">
        <Label htmlFor={id} className="text-sm font-medium">
          {label}
        </Label>
        <p className="text-xs text-muted-foreground">{effect}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Default: {defaultLabel} · Changed by {role}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {!canChange && (
          <Badge variant="outline" className="gap-1 font-normal" data-testid="setting-lock">
            <Lock className="size-3" /> {role}
          </Badge>
        )}
        <fieldset disabled={!canChange} className="contents">
          {children}
        </fieldset>
      </div>
    </div>
  );
}

/** A setting that is a switch: label, effect, default and role, with the toggle on the right. */
export function SwitchRow({ id, checked, onCheckedChange, ...row }: Omit<React.ComponentProps<typeof SettingRow>, 'children'> & { id: string; checked: boolean; onCheckedChange: (v: boolean) => void }) {
  return (
    <SettingRow id={id} {...row}>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} aria-label={typeof row.label === 'string' ? row.label : undefined} />
    </SettingRow>
  );
}
