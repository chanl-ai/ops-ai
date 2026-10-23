'use client';

import type * as React from 'react';
import { type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import Link from 'next/link';

interface EmptyStateAction {
  label: string;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
}

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  testId?: string;
  /** A control that is not a plain button, such as a menu, placed after the actions. */
  children?: React.ReactNode;
}

function ActionButton({
  action,
  variant = 'default',
}: {
  action: EmptyStateAction;
  variant?: 'default' | 'outline';
}) {
  if (action.href) {
    return (
      <Button asChild variant={variant} size="sm">
        <Link href={action.href}>{action.label}</Link>
      </Button>
    );
  }
  return (
    <Button variant={variant} size="sm" onClick={action.onClick} disabled={action.disabled}>
      {action.label}
    </Button>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  secondaryAction,
  testId,
  children,
}: EmptyStateProps) {
  return (
    <div
      className="flex flex-col items-center justify-center py-16 px-8 min-w-0 w-full"
      data-testid={testId ?? 'empty-state'}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted mb-4">
        <Icon className="h-7 w-7 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-semibold mb-1 text-center wrap-break-word">{title}</h3>
      <p className="text-muted-foreground text-center text-sm max-w-sm mb-5 whitespace-normal wrap-break-word">
        {description}
      </p>
      {(action || secondaryAction || children) && (
        <div className="flex items-center gap-3">
          {action && <ActionButton action={action} />}
          {secondaryAction && <ActionButton action={secondaryAction} variant="outline" />}
          {children}
        </div>
      )}
    </div>
  );
}
