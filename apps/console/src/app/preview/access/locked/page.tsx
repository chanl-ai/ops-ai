'use client';

import * as React from 'react';
import { Info, Workflow } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/** Mock (c-150): a button the signed-in person may not use carries an ⓘ that says why and who can grant it. */
export default function LockedMock() {
  return (
    <PageLayout
      icon={Workflow}
      title="Card dispute intake"
      description="Draft version 3 · signed in as Ravi Menon, a viewer of Operations"
      backHref="/workflows"
      actions={
        <div className="flex items-center gap-1.5">
          <Button disabled>Publish</Button>
          <Tooltip defaultOpen>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="size-8" aria-label="Why can't I publish?" data-testid="locked-why">
                <Info className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-72">
              Publishing needs Publish on Workflows, which your Viewer role does not grant. A Builder or Admin of Operations holds it; Priya Shah can grant it.
            </TooltipContent>
          </Tooltip>
        </div>
      }
    >
      <p className="text-sm text-muted-foreground">The workflow editor sits here as it does today; only the locked button and its reason are new.</p>
    </PageLayout>
  );
}
