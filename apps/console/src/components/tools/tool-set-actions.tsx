'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Download, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { AddModuleDialog } from '@/components/tools/add-module-dialog';
import { NewModuleDialog } from '@/components/tools/new-module-dialog';
import { Button } from '@/components/ui/button';
import { useCanBuild } from '@/hooks/me-queries';
import { useCreateBlankModule, useCreateModule, useDiscoverModule } from '@/hooks/tool-module-queries';

/** Import operations and New tool, for a builder: each saves a draft tool set and opens its page. */
export function ToolSetActions() {
  const router = useRouter();
  const canBuild = useCanBuild();
  const discover = useDiscoverModule();
  const create = useCreateModule();
  const createBlank = useCreateBlankModule();
  const [adding, setAdding] = React.useState(false);
  const [creatingBlank, setCreatingBlank] = React.useState(false);
  if (!canBuild) return null;
  return (
    <>
      <Button variant="outline" onClick={() => setAdding(true)} data-testid="import-operations">
        <Download className="size-4" /> Import operations
      </Button>
      <Button onClick={() => setCreatingBlank(true)} data-testid="new-module">
        <Plus className="size-4" /> New tool
      </Button>
      <AddModuleDialog
        open={adding}
        onOpenChange={setAdding}
        onDiscover={(s) => discover.mutateAsync(s)}
        discovering={discover.isPending}
        creating={create.isPending}
        onCreate={async (input) => {
          const m = await create.mutateAsync(input);
          toast.success(`Saved ${m.displayName} as a draft`, { description: 'Rename it, add its credential header and request a security review on its page.' });
          setAdding(false);
          router.push(`/data/tools/${m.id}`);
        }}
      />
      <NewModuleDialog
        open={creatingBlank}
        onOpenChange={setCreatingBlank}
        creating={createBlank.isPending}
        onCreate={async (input) => {
          const m = await createBlank.mutateAsync(input);
          toast.success(`Saved ${m.displayName} as a draft`, { description: 'Add operations here.' });
          setCreatingBlank(false);
          router.push(`/data/tools/${m.id}`);
        }}
      />
    </>
  );
}
