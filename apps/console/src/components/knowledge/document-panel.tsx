'use client';

import { toast } from 'sonner';

import { DocumentSheet } from '@/components/knowledge/document-sheet';
import type { DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { useItem, useKnowledgeLookups, useSetItemOwner, useVerifyItem } from '@/hooks/knowledge-queries';

/** Loads one item and wires the document sheet's actions; shared by a knowledge base's Documents tab and a source's Items tab. */
/** `page`: open on the passages of this page, as a citation names it. */
export function DocumentPanel({ itemId, page, onClose, navigation, onOpenItem }: { itemId: string | null; page?: number; onClose: () => void; navigation?: DetailSheetNavigation; onOpenItem?: (id: string) => void }) {
  const item = useItem(itemId);
  const lookups = useKnowledgeLookups();
  const verify = useVerifyItem();
  const owner = useSetItemOwner();
  const busy = verify.isPending || owner.isPending;
  const it = item.data;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });

  return (
    <DocumentSheet
      open={!!itemId}
      onOpenChange={(o) => !o && onClose()}
      item={it && it.id === itemId ? it : undefined}
      page={page}
      loading={item.isPending}
      error={item.isError ? item.error.message : undefined}
      navigation={navigation}
      owners={lookups.data?.owners ?? []}
      busy={busy}
      onVerify={(verified) =>
        it &&
        verify.mutate(
          { id: it.id, verified },
          { onSuccess: () => toast.success(verified ? 'Marked verified' : 'Verification removed', { description: verified ? 'Review-by date moved to 90 days from today.' : it.title }), onError: fail('update verification') },
        )
      }
      onSetOwner={async (o) => {
        if (!it) return;
        await owner.mutateAsync({ id: it.id, owner: o });
        toast.success(`Owner set to ${o}`);
      }}
      onOpenItem={onOpenItem}
    />
  );
}
