import * as React from 'react';

import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

/** Label, control, then hint or error. Optional fields say so in the label, per the admin dialog rules. */
export function FormField({
  id,
  label,
  optional,
  required,
  hint,
  error,
  children,
  className,
}: {
  id: string;
  label: string;
  optional?: boolean;
  /** Marks the label for forms where most fields are optional, e.g. ones generated from an input schema. */
  required?: boolean;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={id}>
        {label}
        {optional && <span className="font-normal text-muted-foreground">(optional)</span>}
        {required && (
          <span className="text-destructive" aria-hidden>
            *
          </span>
        )}
        {required && <span className="sr-only">(required)</span>}
      </Label>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * A group of controls under one label, such as a list of checkboxes: a `fieldset` with a `legend`, so the label names the
 * group for a screen reader. `FormField` labels one control by `htmlFor`, which a group of several has no id for.
 */
export function FormFieldGroup({ label, optional, hint, error, children, className }: { label: string; optional?: boolean; hint?: React.ReactNode; error?: string; children: React.ReactNode; className?: string }) {
  const noteId = React.useId();
  const note = error ?? hint;
  return (
    <fieldset className={cn('flex min-w-0 flex-col gap-2', className)} aria-describedby={note ? noteId : undefined} aria-invalid={error ? true : undefined}>
      <legend className="mb-2 flex items-center gap-2 text-sm leading-none font-medium">
        {label}
        {optional && <span className="font-normal text-muted-foreground">(optional)</span>}
      </legend>
      {children}
      {note ? (
        <p id={noteId} className={cn('text-xs', error ? 'text-destructive' : 'text-muted-foreground')}>
          {note}
        </p>
      ) : null}
    </fieldset>
  );
}

/** Stops a click inside a clickable table row (menus, switches) from also opening the row. */
/** `align="start"` for editable cells under a left-aligned column header; the default suits trailing action cells. */
export function StopRowClick({ children, align = 'end' }: { children: React.ReactNode; align?: 'start' | 'end' }) {
  return (
    <div onClick={(e) => e.stopPropagation()} className={align === 'start' ? 'flex justify-start' : 'flex justify-end'}>
      {children}
    </div>
  );
}
