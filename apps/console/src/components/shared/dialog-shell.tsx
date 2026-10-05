'use client';

/**
 * DialogShell — the shared dialog geometry wrapper (sizes in `apps/console/CLAUDE.md`).
 *
 * `DialogContent` from the shadcn primitive caps only width — no max-height, no
 * scroll containment, and its layout is `grid`, not `flex flex-col`. Content taller
 * than the viewport clips at BOTH ends: Radix centers the panel with
 * `translate-y-[-50%]` and scroll-locks the page, so an overflowing dialog traps the
 * user with an unreachable footer. Every dialog needs a fixed header, ONE scrolling
 * body, and a fixed footer inside a height-capped, `flex flex-col` panel — this is
 * that skeleton, pasted once instead of per call site.
 *
 * Dialogs never scroll the page; wide before tall. Prefer a wider `size` over a
 * taller body when content doesn't fit — see the `size` scale in admin-dialogs.md.
 */
import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

type DialogSize = 'sm' | 'md' | 'lg' | 'xl' | 'fullscreen';

export interface DialogShellProps extends Omit<
  React.ComponentProps<typeof DialogContent>,
  'size' | 'children' | 'className' | 'title'
> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Radix `Dialog`'s `modal` prop, forwarded — `false` for a dialog opened from inside another open Dialog. */
  modal?: boolean;
  size?: DialogSize;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Rendered below the title/description, inside the fixed header (e.g. a `Stepper`). */
  headerExtra?: React.ReactNode;
  /** Fixed footer content. Rendered inside `DialogFooter` — pass your own `<div className="flex w-full ...">` for custom alignment (Back/Cancel/Next layouts), same as before this wrapper existed. */
  footer?: React.ReactNode;
  /** Scrolling body content. */
  children: React.ReactNode;
  /** Extra classes on the `DialogContent` panel itself. */
  panelClassName?: string;
  /** Extra classes on the scrolling body div. */
  bodyClassName?: string;
  /** Ref on the scrolling body div — e.g. for "scroll to top on step change" in wizard steps. */
  bodyRef?: React.Ref<HTMLDivElement>;
}

export function DialogShell({
  open,
  onOpenChange,
  modal,
  size,
  title,
  description,
  headerExtra,
  footer,
  children,
  panelClassName,
  bodyClassName,
  bodyRef,
  showCloseButton,
  ...contentProps
}: DialogShellProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} modal={modal}>
      <DialogContent
        size={size}
        showCloseButton={showCloseButton}
        className={cn('flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0', panelClassName)}
        {...contentProps}
      >
        <DialogHeader className="shrink-0 border-b px-6 py-4 pr-12">
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
          {headerExtra}
        </DialogHeader>

        <div
          ref={bodyRef}
          className={cn('min-h-0 flex-1 overflow-y-auto px-6 py-4', bodyClassName)}
        >
          {children}
        </div>

        {footer && (
          <DialogFooter className="w-full shrink-0 flex-row items-center border-t px-6 py-4 sm:justify-end">
            {footer}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
