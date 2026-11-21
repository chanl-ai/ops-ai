'use client';

import * as React from 'react';
import { Users } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

/**
 * A newer copy was saved by someone else while this page held changes of its own: the page shows the newer copy, keeps
 * the other one read-only beside it, and saves nothing over the newer copy until the person picks an action. The
 * editor owns what each action does; this draws the notice, the open/close toggle for the kept copy and the actions.
 * Test ids: `testId` on the notice, `${testId}-open` on the toggle.
 */
export function NewerCopyNotice({ testId, title, children, copyOpen, onToggleCopy, openLabel = 'Open my copy', closeLabel = 'Hide my copy', actions }: { testId: string; title: string; children: React.ReactNode; copyOpen: boolean; onToggleCopy: () => void; openLabel?: string; closeLabel?: string; actions?: React.ReactNode }) {
  return (
    <Alert data-testid={testId}>
      <Users />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <div>{children}</div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onToggleCopy} aria-pressed={copyOpen} data-testid={`${testId}-open`}>
            {copyOpen ? closeLabel : openLabel}
          </Button>
          {actions}
        </div>
      </AlertDescription>
    </Alert>
  );
}
