'use client';

import { EyeOff, Lock } from 'lucide-react';

import type { PermissionScope } from '@/lib/types/run-as';
import { cn } from '@/lib/utils';

/** What one answer could not use because of who it ran as. Shows nothing when permissions hid nothing. */
export function PermissionNote({ scope, className }: { scope?: PermissionScope; className?: string }) {
  if (!scope || (!scope.hiddenDocuments && !scope.blockedTools.length)) return null;
  return (
    <div className={cn('flex flex-col gap-1 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground', className)} data-testid="permission-note">
      {scope.hiddenDocuments > 0 && (
        <span className="flex items-center gap-1.5">
          <EyeOff className="size-3.5 shrink-0" />
          Hidden by permissions: {scope.hiddenDocuments} {scope.hiddenDocuments === 1 ? 'document' : 'documents'}
          {scope.hiddenCollections.length > 0 && <> in {scope.hiddenCollections.join(', ')}</>} · running as {scope.runAsName}
        </span>
      )}
      {scope.blockedTools.length > 0 && (
        <span className="flex items-center gap-1.5">
          <Lock className="size-3.5 shrink-0" />
          Not entitled: {scope.blockedTools.join(', ')}
        </span>
      )}
    </div>
  );
}
