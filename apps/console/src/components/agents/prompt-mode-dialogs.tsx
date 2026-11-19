'use client';

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import type { PromptMode } from '@/lib/types/domain';

const COPY: Record<PromptMode, { title: string; body: string; action: string }> = {
  full: {
    title: 'Edit as plain text?',
    body: 'The prompt as it reads now is copied into a text box and becomes the prompt. Your brief stays saved, and only Never is still used from it. You can come back to the brief at any time.',
    action: 'Edit as plain text',
  },
  brief: {
    title: 'Go back to the brief?',
    body: 'The next version uses the prompt written from the brief headings. Your plain text stays saved but is not used.',
    action: 'Use the brief',
  },
};

/** Asks before the agent's prompt switches between the brief and plain text; the switch is a save on the draft. */
export function PromptModeDialogs({ to, onCancel, onConfirm, pending }: { to: PromptMode | null; onCancel: () => void; onConfirm: (to: PromptMode) => void; pending?: boolean }) {
  const copy = COPY[to ?? 'full'];
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
