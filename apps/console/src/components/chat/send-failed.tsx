'use client';

import { AlertTriangle } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

/**
 * A message the service refused or could not take, with its reason, Retry and Dismiss. One alert for every chat: the
 * console's, the agent test panel's and the embedded widget's, so a refused send is never dropped without a word.
 */
export function SendFailedAlert({ message, onRetry, onDismiss }: { message: string; onRetry: () => void; onDismiss: () => void }) {
  return (
    <Alert variant="destructive" data-testid="send-failed">
      <AlertTriangle className="size-4" />
      <AlertTitle>Your message wasn’t sent</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>{message}</p>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" onClick={onRetry}>
            Retry
          </Button>
          <Button size="sm" variant="ghost" className="text-foreground" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
