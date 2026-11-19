'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { buttonVariants } from '@/components/ui/button';
import { useLeaveGuard } from '@/hooks/use-leave-guard';

/**
 * Holds a person on a page while it has text a save has not stored. A link to another console page opens a dialog
 * that asks first; closing or reloading the tab gets the browser's own question (`useLeaveGuard`). `failed` says the
 * last save did not go through, which the dialog names.
 *
 * The router has no way to hold a navigation, so the link's click is caught before the router sees it. A button that
 * navigates in code, and the browser's Back, are not held.
 */
export function LeaveGuard({ unsaved, failed }: { unsaved: boolean; failed?: boolean }) {
  const router = useRouter();
  const [to, setTo] = React.useState<string | null>(null);
  useLeaveGuard(unsaved);

  React.useEffect(() => {
    if (!unsaved) return;
    const hold = (e: MouseEvent) => {
      // A click that opens a new tab or window leaves this page as it is.
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const link = e.target instanceof Element ? e.target.closest<HTMLAnchorElement>('a[href]') : null;
      if (!link || (link.target && link.target !== '_self') || link.hasAttribute('download')) return;
      const url = new URL(link.href, window.location.href);
      // Another site is the browser's question; the same page (a tab, an anchor) keeps this form mounted.
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname) return;
      e.preventDefault();
      e.stopPropagation();
      setTo(`${url.pathname}${url.search}${url.hash}`);
    };
    window.addEventListener('click', hold, true);
    return () => window.removeEventListener('click', hold, true);
  }, [unsaved]);

  return (
    <AlertDialog open={to !== null} onOpenChange={(open) => !open && setTo(null)}>
      <AlertDialogContent data-testid="leave-guard">
        <AlertDialogHeader>
          <AlertDialogTitle>Discard changes?</AlertDialogTitle>
          <AlertDialogDescription>{failed ? 'Your last change couldn’t be saved. Leaving now loses it.' : 'Your changes are not saved. Leaving now loses them.'}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction
            className={buttonVariants({ variant: 'destructive' })}
            data-testid="leave-guard-discard"
            onClick={() => {
              if (to !== null) router.push(to);
            }}
          >
            Discard changes
          </AlertDialogAction>
          {/* The dialog opens with this button in focus, so Enter stays on the page. */}
          <AlertDialogCancel data-testid="leave-guard-keep">Keep editing</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
