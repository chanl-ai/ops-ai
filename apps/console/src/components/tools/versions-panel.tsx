'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { shortDate } from '@/lib/format';
import type { ChangeKind, ModuleVersion, OperationChange } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

import { ENV_LABEL } from './module-meta';

const KIND: Record<ChangeKind, string> = { added: 'Added', removed: 'Hidden', access_widened: 'Access widened', schema_changed: 'Schema', binding_changed: 'Binding', settings: 'Settings' };
const STATUS: Record<ModuleVersion['status'], string> = { draft: 'Draft', in_review: 'In security review', published: 'Published', deprecated: 'Superseded', revoked: 'Revoked' };

/** Changes in one version, major ones first. */
export function ChangeList({ changes }: { changes: OperationChange[] }) {
  if (!changes.length) return <p className="text-sm text-muted-foreground">No operation changes.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {[...changes]
        .sort((a, b) => Number(b.major) - Number(a.major))
        .map((c, i) => (
          <li key={`${c.operation}-${c.kind}-${i}`} className="rounded-md border p-2">
            <div className="flex flex-wrap items-center gap-2">
              <code className="font-mono text-xs">{c.operation}</code>
              <Badge variant={c.major ? 'destructive' : 'secondary'} className="text-[11px]">
                {c.major ? 'Major' : 'Minor'}
              </Badge>
              <span className="text-xs text-muted-foreground">{KIND[c.kind]}</span>
            </div>
            <p className={cn('mt-1 text-sm', c.major ? 'text-foreground' : 'text-muted-foreground')}>{c.detail}</p>
          </li>
        ))}
    </ul>
  );
}

export function ViewChangesDialog({ version, onOpenChange }: { version: ModuleVersion | null; onOpenChange: (open: boolean) => void }) {
  const major = version?.changes.some((c) => c.major);
  return (
    <DialogShell
      open={!!version}
      onOpenChange={onOpenChange}
      size="md"
      title={`Changes in v${version?.version ?? ''}`}
      description={major ? 'A major version: Security reviews it, and each workflow needs a new approval before it can move to it.' : 'A minor version: workflows take it at their next publish, which re-runs their tests. No new approval.'}
      footer={
        <div className="flex w-full justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </div>
      }
    >
      {version && (
        <div className="flex flex-col gap-3">
          {version.note && <p className="text-sm">{version.note}</p>}
          <ChangeList changes={version.changes} />
        </div>
      )}
    </DialogShell>
  );
}

/** Every version of the module, which workflows pin each one, and whether the gateway reached it. */
export function VersionsPanel({ versions }: { versions: ModuleVersion[] }) {
  const [open, setOpen] = React.useState<ModuleVersion | null>(null);
  return (
    <>
      <div className="overflow-x-auto rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Published</TableHead>
              <TableHead>Pinned by</TableHead>
              <TableHead>Reachability</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {versions.map((v) => (
              <TableRow key={v.version}>
                <TableCell className="min-w-56">
                  <span className="font-mono text-sm font-medium">v{v.version}</span>
                  {v.changes.some((c) => c.major) && (
                    <Badge variant="outline" className="ml-2 text-[11px]">
                      Major
                    </Badge>
                  )}
                  <div className="text-xs text-muted-foreground">{v.note}</div>
                </TableCell>
                <TableCell className="text-sm whitespace-nowrap">{STATUS[v.status]}</TableCell>
                <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                  {v.publishedAt ? shortDate(v.publishedAt) : 'Not yet'}
                  <div>{v.publishedBy}</div>
                </TableCell>
                <TableCell className="text-sm">{v.pinnedBy.length ? v.pinnedBy.map((w) => w.name).join(', ') : <span className="text-xs text-muted-foreground">None</span>}</TableCell>
                <TableCell className="text-xs whitespace-nowrap">
                  {v.reachability.map((r) => (
                    <div key={r.environment} className={r.ok ? 'text-muted-foreground' : 'font-medium text-red-600 dark:text-red-400'}>
                      {ENV_LABEL[r.environment]} {r.ok ? 'reachable' : 'unreachable'}
                    </div>
                  ))}
                </TableCell>
                <TableCell>
                  <Button size="sm" variant="ghost" onClick={() => setOpen(v)}>
                    View changes
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ViewChangesDialog version={open} onOpenChange={(o) => !o && setOpen(null)} />
    </>
  );
}
