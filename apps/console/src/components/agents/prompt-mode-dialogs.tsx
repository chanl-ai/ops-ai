'use client';

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import type { PromptMode } from '@/lib/types/domain';

const COPY = {
  title: 'Move into the brief?',
  body: 'Your plain text is placed under How to answer, word for word, and the next version uses the prompt written from the brief. Check it with View prompt before you publish.',
  action: 'Move into the brief',
};

/** Asks before an agent still in plain text moves into the brief; the move is a save on the draft. */
export function PromptModeDialogs({ to, onCancel, onConfirm, pending }: { to: PromptMode | null; onCancel: () => void; onConfirm: (to: PromptMode) => void; pending?: boolean }) {
  const copy = COPY;
  return (
    <AlertDialog open={to !== null} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent data-testid="prompt-mode-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>{copy.body}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction disabled={pending} onClick={() => to && onConfirm(to)} data-testid="prompt-mode-confirm">
            {copy.action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
