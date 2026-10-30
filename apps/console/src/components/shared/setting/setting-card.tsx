'use client';

import type { FormEvent, ReactNode } from 'react';
import { Lock } from 'lucide-react';

import { LoadingButton } from '@/components/shared/loading-button';
import { useIsSample } from '@/components/shared/sample-data';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';

/**
 * One setting, one card, one Save. The footer carries the constraint or a link on the left and the Save on the right;
 * when the person lacks the role, the Save is replaced by the lock and the role's name, and the controls are off.
 * A setting another person depends on commits here, never inside a page-wide form.
 */
export function SettingCard({
  id,
  title,
  description,
  children,
  help,
  aside,
  onSave,
  saving,
  dirty = true,
  saveLabel = 'Save',
  requiredRole,
  locked,
  footerEnd,
  tone,
}: {
  id?: string;
  title: ReactNode;
  description?: ReactNode;
  /** The control. */
  children?: ReactNode;
  /** Left side of the footer: the constraint ("Use 32 characters at most.") or a link. */
  help?: ReactNode;
  /** Right side of the header, such as an avatar. */
  aside?: ReactNode;
  onSave?: () => void | Promise<void>;
  saving?: boolean;
  dirty?: boolean;
  saveLabel?: string;
  /** The role that may change this setting; shown in the footer when `locked`. */
  requiredRole?: string;
  locked?: boolean;
  /** Replaces the Save button (a gated card puts its price and action here). */
  footerEnd?: ReactNode;
  tone?: 'default' | 'danger';
}) {
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!locked && dirty) void onSave?.();
  };
  // A sample card offers no Save or action at all: a control that cannot store anything reads as broken when it is
  // only switched off.
  const sample = useIsSample();
  const hasFooter = help || ((footerEnd || onSave || locked) && !sample);
  return (
    <form id={id} onSubmit={submit} className="scroll-mt-20" data-testid={id ? `setting-${id}` : undefined}>
      <Card className={tone === 'danger' ? 'gap-0 border-destructive/40' : 'gap-0'}>
        <CardHeader className="flex flex-row items-start justify-between gap-4 pb-4">
          <div className="grid min-w-0 gap-1.5">
            <CardTitle className="text-base">{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </div>
          {aside}
        </CardHeader>
        {children && (
          <CardContent className="pb-6">
            <fieldset disabled={locked} className="contents">
              {children}
            </fieldset>
          </CardContent>
        )}
        {hasFooter && (
          <CardFooter className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/40 px-6 py-3">
            <div className="min-w-0 text-xs text-muted-foreground">{help}</div>
            {sample ? null : footerEnd ??
              (locked ? (
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="setting-lock">
                  <Lock className="size-3.5" /> Only {requiredRole ? `a ${requiredRole}` : 'an admin'} can change this
                </span>
              ) : onSave ? (
                <LoadingButton type="submit" size="sm" isLoading={saving} disabled={!dirty}>
                  {saveLabel}
                </LoadingButton>
              ) : null)}
          </CardFooter>
        )}
      </Card>
    </form>
  );
}
