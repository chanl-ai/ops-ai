'use client';

import type { ReactNode } from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';

export interface FormShellProps {
  /** `card` is the settings page's own section; `dialog` is the same form opened in place from another page. */
  shell: 'card' | 'dialog';
  title: string;
  description: string;
  submitLabel: string;
  onSubmit: () => void | Promise<void>;
  pending?: boolean;
  /** Dialog only. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  help?: ReactNode;
  locked?: boolean;
  requiredRole?: string;
  id?: string;
  children: ReactNode;
}

/**
 * The one place a settings form chooses its shell. A form component renders its fields once, inside this, and the
 * page passes `card` while any other page passes `dialog`; the fields, validation and server call do not differ.
 */
export function FormShell({ shell, title, description, submitLabel, onSubmit, pending, open = false, onOpenChange, help, locked, requiredRole, id, children }: FormShellProps) {
  if (shell === 'card')
    return (
      <SettingCard id={id} title={title} description={description} help={help} onSave={onSubmit} saving={pending} saveLabel={submitLabel} locked={locked} requiredRole={requiredRole}>
        {children}
      </SettingCard>
    );
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange ?? (() => undefined)}
      size="md"
      title={title}
      description={description}
      onSubmit={onSubmit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange?.(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={pending}>
            {submitLabel}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">{children}</div>
    </DialogShell>
  );
}
