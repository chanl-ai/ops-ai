'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { AddMetadataDialog } from '@/components/knowledge/add-metadata-dialog';
import { DocumentSheet } from '@/components/knowledge/document-sheet';
import type { DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { useExcludeItems, useItem, useKnowledgeLookups, useReprocessItems, useSetItemMetadata, useSetItemOwner, useSetItemTags, useVerifyItem } from '@/hooks/knowledge-queries';

/** Loads one item and wires the document sheet's actions; shared by a knowledge base's Documents tab and a source's Items tab. */
export function DocumentPanel({ itemId, onClose, navigation, onOpenItem }: { itemId: string | null; onClose: () => void; navigation?: DetailSheetNavigation; onOpenItem?: (id: string) => void }) {
  const metadata = useSetItemMetadata();
  const [fixing, setFixing] = React.useState(false);
  const item = useItem(itemId);
  const lookups = useKnowledgeLookups();
  const reprocess = useReprocessItems();
  const exclude = useExcludeItems();
  const verify = useVerifyItem();
  const tags = useSetItemTags();
  const owner = useSetItemOwner();
  const busy = reprocess.isPending || exclude.isPending || verify.isPending || tags.isPending || owner.isPending || metadata.isPending;
  const it = item.data;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });

  return (
    <>
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
      onAddMetadata={() => setFixing(true)}
      onOpenItem={onOpenItem}
    />
    <AddMetadataDialog
      open={fixing}
      onOpenChange={setFixing}
      item={it}
      isPending={metadata.isPending}
      onSubmit={async (values) => {
        if (!it) return;
        const next = await metadata.mutateAsync({ id: it.id, values });
        toast.success(next.status === 'held' ? `${next.title} is still held` : `${next.title} is searchable`, { description: next.status === 'held' ? `Still missing ${next.held?.missing.join(', ')}.` : 'Its knowledge bases include it from the next query.' });
      }}
    />
    </>
  );
}
