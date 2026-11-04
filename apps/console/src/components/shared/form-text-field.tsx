'use client';

import type * as React from 'react';
import type { Control, FieldPath, FieldValues } from 'react-hook-form';

import { FormControl, FormDescription, FormField as RegistryFormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

/**
 * One text field of a react-hook-form form, with the console's field look (label, "(optional)", hint, then its error
 * in place of the hint). The error is the form's, from its schema, so every form built on this shows errors the same way.
 */
export function FormTextField<T extends FieldValues>({
  control,
  name,
  label,
  optional,
  hint,
  type = 'text',
  multiline,
  placeholder,
  testId,
  className,
  trailing,
}: {
  control: Control<T>;
  name: FieldPath<T>;
  label: string;
  optional?: boolean;
  hint?: React.ReactNode;
  type?: 'text' | 'password' | 'url';
  multiline?: boolean;
  placeholder?: string;
  testId?: string;
  className?: string;
  /** A control beside the input, such as Copy. */
  trailing?: React.ReactNode;
}) {
  return (
    <RegistryFormField
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <FormItem className={cn('flex flex-col gap-1.5', className)}>
          <FormLabel>
            {label}
            {optional && <span className="font-normal text-muted-foreground">(optional)</span>}
          </FormLabel>
          <div className="flex min-w-0 items-center gap-1">
            <FormControl>
              {multiline ? (
                <Textarea {...field} value={field.value ?? ''} placeholder={placeholder} className="font-mono text-xs" data-testid={testId} />
              ) : (
                <Input {...field} value={field.value ?? ''} type={type} placeholder={placeholder} autoComplete="off" data-testid={testId} />
              )}
            </FormControl>
            {trailing}
          </div>
          {fieldState.error ? (
            <FormMessage className="text-xs" data-testid={testId ? `${testId}-error` : undefined} />
          ) : hint ? (
            <FormDescription className="text-xs">{hint}</FormDescription>
          ) : null}
        </FormItem>
      )}
    />
  );
}
