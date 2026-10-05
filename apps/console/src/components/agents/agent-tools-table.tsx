'use client';

import { UserCheck, Wrench, X } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { AccessBadge, ToolTypeBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count } from '@/lib/format';
import type { Tool } from '@/lib/types/domain';

/** Tools granted to one agent, with how each one is supervised; revoking is per row. */
export function AgentToolsTable({
  tools,
  loading,
  onGrant,
  onRevoke,
  revoking,
}: {
  tools: Tool[];
  loading: boolean;
  onGrant: () => void;
  onRevoke: (tool: Tool) => void;
  revoking: boolean;
}) {
  if (loading)
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  if (!tools.length) return <EmptyState icon={Wrench} title="No tools granted" description="Without tools the agent can only answer from knowledge." action={{ label: 'Grant tools', onClick: onGrant }} />;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {tools.length} tool{tools.length === 1 ? '' : 's'} · {tools.filter((t) => t.requiresReview).length} pause for review on every call
        </p>
        <Button size="sm" variant="outline" onClick={onGrant}>
          <Wrench className="size-3.5" /> Grant tools
        </Button>
      </div>
      <div className="overflow-hidden rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tool</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>System</TableHead>
              <TableHead>Access</TableHead>
              <TableHead>Review</TableHead>
              <TableHead className="text-right">Calls · 24h</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {tools.map((t) => (
              <TableRow key={t.id}>
                <TableCell>
                  <code className="font-mono text-sm">{t.name}</code>
                  <div className="text-xs text-muted-foreground">{t.description}</div>
                </TableCell>
                <TableCell>
                  <ToolTypeBadge type={t.type} />
                </TableCell>
                <TableCell className="text-muted-foreground">{t.system}</TableCell>
                <TableCell>
                  <AccessBadge access={t.access} />
                </TableCell>
                <TableCell>
                  {t.requiresReview ? (
                    <span className="inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
                      <UserCheck className="size-3.5" /> Every call
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">Workflow gates only</span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">{count(t.calls24h)}</TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" className="size-8" aria-label={`Revoke ${t.name}`} disabled={revoking} onClick={() => onRevoke(t)}>
                    <X className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
