'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

/** Choose which knowledge collections an agent may search and cite. */
export function CollectionsDialog({
  open,
  onOpenChange,
  collections,
  selected,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  collections: string[];
  selected: string[];
  onSubmit: (collections: string[]) => Promise<unknown>;
  isPending: boolean;
}) {
  const [picked, setPicked] = React.useState<Set<string>>(new Set(selected));
  React.useEffect(() => {
    if (open) setPicked(new Set(selected));
  }, [open, selected]);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title="Knowledge collections"
      description="The agent can cite only documents in the collections ticked here."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            onClick={async () => {
              await onSubmit([...picked]);
              onOpenChange(false);
            }}
          >
            Save collections
          </LoadingButton>
        </div>
      }
    >
      <ul className="flex flex-col divide-y rounded-lg border">
        {collections.map((c) => (
          <li key={c}>
            <label htmlFor={`col-${c}`} className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-muted/40">
              <Checkbox
                id={`col-${c}`}
                checked={picked.has(c)}
                onCheckedChange={(v) =>
                  setPicked((s) => {
                    const n = new Set(s);
                    if (v) n.add(c);
                    else n.delete(c);
                    return n;
                  })
                }
              />
              <span className="text-sm">{c}</span>
            </label>
          </li>
        ))}
      </ul>
    </DialogShell>
  );
}
