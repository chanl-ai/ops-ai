'use client';

import { toast } from 'sonner';

import { toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { useRemoveFiles } from '@/hooks/file-queries';
import { useSticky } from '@/hooks/use-sticky';
import type { FileRecord } from '@/lib/types/files';

/**
 * Deletes files through the delete guard: the service skips each file still used, held or inside a retention period
 * that must run out, and names why. Any page that lists files reuses it, so a file is never deleted around the guard.
 */
export function DeleteFilesDialog({ files, onOpenChange, onDeleted }: { files: FileRecord[] | null; onOpenChange: (open: boolean) => void; onDeleted?: (ids: string[]) => void }) {
  const remove = useRemoveFiles();
  const shown = useSticky(files);
  const nameOf = (id: string) => shown?.find((f) => f.id === id)?.name ?? id;
  return (
    <DeleteDialog
      open={!!files}
      onOpenChange={onOpenChange}
      entityType="file"
      entityName={shown?.length === 1 ? shown[0].name : undefined}
      count={shown?.length}
      description="Every version is deleted from storage. Files still used by a source, case, chat or test set, under legal hold, or inside a retention period that must run out are skipped and named."
      isLoading={remove.isPending}
      onConfirm={async () => {
        if (!files) return;
        try {
          const res = await remove.mutateAsync(files.map((f) => f.id));
          toastBulk(res, 'Deleted', 'file', nameOf);
          onDeleted?.(res.updated);
          onOpenChange(false);
        } catch (e) {
          toast.error('Couldn’t delete', { description: (e as Error).message });
        }
      }}
    />
  );
}
