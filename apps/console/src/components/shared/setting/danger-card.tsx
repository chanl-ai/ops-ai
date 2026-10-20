'use client';

import * as React from 'react';

import { DestructiveDialog } from '@/components/shared/setting/destructive-dialog';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';

/** Transfer, leave or delete as its own card: a red action and a footer that states the precondition. */
export function DangerCard({ title, description, precondition, action, confirmName, onConfirm, blockedReason }: { title: string; description: string; precondition: string; action: string; confirmName: string; onConfirm: () => void | Promise<void>; blockedReason?: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <SettingCard
        tone="danger"
        title={title}
        description={description}
        help={blockedReason ?? precondition}
        footerEnd={
          <Button type="button" variant="destructive" size="sm" disabled={!!blockedReason} onClick={() => setOpen(true)}>
            {action}
          </Button>
        }
      />
      <DestructiveDialog open={open} onOpenChange={setOpen} title={`${action}?`} description={description} confirmName={confirmName} actionLabel={action} onConfirm={async () => (await onConfirm(), setOpen(false))} />
    </>
  );
}
