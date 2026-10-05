'use client';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import type { ChangeConflict, KnowledgeChange } from '@/lib/types/knowledge-changes';

type Resolution = NonNullable<ChangeConflict['resolution']>;

/**
 * Settles a conflict between a proposed change and another document before the change can be approved. Adapted
 * from the shared component library's conflict dialog (two explicit outcomes, both keep every version).
 */
export function ResolveConflictDialog({
  open,
  onOpenChange,
  change,
  pending,
  onResolve,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  change: KnowledgeChange | null;
  pending: Resolution | null;
  onResolve: (resolution: Resolution) => void;
}) {
  const c = change?.conflict;
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={c ? `Resolve conflict with ${c.documentTitle}` : 'Resolve conflict'}
      description="Agents would find both passages and could cite either. Choose which one they should follow. Both documents keep every version."
      footer={
        <div className="flex w-full flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={!!pending}>
            Cancel
          </Button>
          <LoadingButton variant="outline" isLoading={pending === 'keep_both'} disabled={!!pending} onClick={() => onResolve('keep_both')}>
            Keep both, prefer this change
          </LoadingButton>
          <LoadingButton isLoading={pending === 'supersede_other'} disabled={!!pending} onClick={() => onResolve('supersede_other')}>
            Mark {c?.documentTitle ?? 'the other document'} superseded
          </LoadingButton>
        </div>
      }
    >
      {change && c && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs font-medium text-muted-foreground">Proposed in {change.documentTitle}</div>
            <p className="mt-1 text-sm whitespace-pre-wrap">{change.after}</p>
          </div>
          <div className="min-w-0 rounded-md border border-red-600/30 bg-red-500/5 p-3">
            <div className="text-xs font-medium text-muted-foreground">
              Currently in {c.documentTitle} · {c.sourceName}
            </div>
            <p className="mt-1 text-sm whitespace-pre-wrap">{c.passage}</p>
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            Superseding excludes the other document from answers until it is updated at its source. Keeping both adds a precedence rule so agents follow this change when the two disagree.
          </p>
        </div>
      )}
    </DialogShell>
  );
}
