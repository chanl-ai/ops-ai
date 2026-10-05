'use client';

import { toast } from 'sonner';

import { DocumentSheet } from '@/components/knowledge/document-sheet';
import type { DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { useExcludeItems, useItem, useKnowledgeLookups, useReprocessItems, useSetItemOwner, useSetItemTags, useVerifyItem } from '@/hooks/knowledge-queries';

/** Loads one item and wires the document sheet's actions; shared by a knowledge base's Documents tab and a source's Items tab. */
export function DocumentPanel({ itemId, onClose, navigation }: { itemId: string | null; onClose: () => void; navigation?: DetailSheetNavigation }) {
  const item = useItem(itemId);
  const lookups = useKnowledgeLookups();
  const reprocess = useReprocessItems();
  const exclude = useExcludeItems();
  const verify = useVerifyItem();
  const tags = useSetItemTags();
  const owner = useSetItemOwner();
  const busy = reprocess.isPending || exclude.isPending || verify.isPending || tags.isPending || owner.isPending;
  const it = item.data;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });

  return (
    <DocumentSheet
      open={!!itemId}
      onOpenChange={(o) => !o && onClose()}
      item={it && it.id === itemId ? it : undefined}
      loading={item.isPending}
      error={item.isError ? item.error.message : undefined}
      navigation={navigation}
      owners={lookups.data?.owners ?? []}
      busy={busy}
      onReprocess={() => it && reprocess.mutate([it.id], { onSuccess: () => toast.success(`Reprocessing ${it.title}`), onError: fail('reprocess') })}
      onVerify={(verified) =>
        it &&
        verify.mutate(
          { id: it.id, verified },
          { onSuccess: () => toast.success(verified ? 'Marked verified' : 'Verification removed', { description: verified ? 'Review-by date moved to 90 days from today.' : it.title }), onError: fail('update verification') },
        )
      }
      onExclude={() =>
        it &&
        exclude.mutate([it.id], {
          onSuccess: () => {
            toast.success(`Excluded ${it.title}`, { description: 'An exclude rule for its path was added to the source.' });
            onClose();
          },
          onError: fail('exclude'),
        })
      }
      onSetTags={(t) => it && tags.mutate({ id: it.id, tags: t }, { onError: fail('save tags') })}
      onSetOwner={async (o) => {
        if (!it) return;
        await owner.mutateAsync({ id: it.id, owner: o });
        toast.success(`Owner set to ${o}`);
      }}
    />
  );
}
