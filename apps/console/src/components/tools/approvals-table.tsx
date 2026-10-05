'use client';

import { Check, MoreHorizontal, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { relativeTime } from '@/lib/format';
import type { ModuleApproval, ModuleOperation } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

import { ApprovalStatusBadge, ENV_LABEL, ExpiryText } from './module-meta';

/** Workflow approvals for one module: which operations each may call, until when. Requests are decided inline. */
export function ApprovalsTable({
  approvals,
  operations,
  currentUser,
  onDecide,
  onRevoke,
  busy,
}: {
  approvals: ModuleApproval[];
  operations: ModuleOperation[];
  currentUser: string;
  onDecide: (a: ModuleApproval, decision: 'approved' | 'rejected') => void;
  onRevoke: (a: ModuleApproval) => void;
  busy: boolean;
}) {
  const money = new Set(operations.filter((o) => o.fourEyes).map((o) => o.name));
  return (
    <div className="overflow-x-auto rounded-md border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Workflow</TableHead>
            <TableHead>Operations</TableHead>
            <TableHead>Environment</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Expiry</TableHead>
            <TableHead>Decided</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {approvals.map((a) => {
            const open = a.status === 'requested';
            const mine = a.requestedBy === currentUser;
            return (
              <TableRow key={a.id} className={cn((a.status === 'revoked' || a.status === 'rejected') && 'opacity-60')}>
                <TableCell className="min-w-48">
                  <div className="font-medium">{a.workflowName}</div>
                  <div className="max-w-72 truncate text-xs text-muted-foreground" title={a.justification}>
                    {a.justification}
                  </div>
                  {a.constraints && <div className="text-xs text-muted-foreground">Limit: {a.constraints}</div>}
                </TableCell>
                <TableCell className="min-w-56">
                  <span className="flex flex-wrap gap-1">
                    {a.operations.map((o) => (
                      <code key={o} className={cn('rounded border px-1 font-mono text-[11px]', money.has(o) && 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300')}>
                        {o}
                      </code>
                    ))}
                  </span>
                  <span className="text-[11px] text-muted-foreground">Major version {a.major}</span>
                </TableCell>
                <TableCell className="text-sm">{ENV_LABEL[a.environment]}</TableCell>
                <TableCell>
                  <ApprovalStatusBadge status={a.status} />
                </TableCell>
                <TableCell>{a.status === 'approved' || a.status === 'expired' ? <ExpiryText at={a.expiresAt} /> : <span className="text-xs text-muted-foreground">{open && a.expiresAt ? `Asks until ${new Date(a.expiresAt).toLocaleDateString('en-CA', { dateStyle: 'medium' })}` : '—'}</span>}</TableCell>
                <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                  {a.decidedBy ? (
                    <>
                      {a.decidedBy}
                      <div>{relativeTime(a.decidedAt)}</div>
                      {a.reason && <div className="max-w-40 truncate" title={a.reason}>{a.reason}</div>}
                    </>
                  ) : (
                    <>
                      Requested by {a.requestedBy}
                      <div>{relativeTime(a.requestedAt)}</div>
                    </>
                  )}
                </TableCell>
                <TableCell>
                  {open ? (
                    <div className="flex gap-1">
                      <Button size="sm" variant="outline" disabled={busy || mine} title={mine ? 'You requested this; someone else in the owner team decides it' : undefined} onClick={() => onDecide(a, 'approved')}>
                        <Check className="size-3.5" /> Approve
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busy || mine} onClick={() => onDecide(a, 'rejected')} aria-label={`Reject ${a.workflowName}`}>
                        <X className="size-3.5" />
                      </Button>
                    </div>
                  ) : a.status === 'approved' ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="icon" variant="ghost" className="size-8" aria-label={`Actions for ${a.workflowName}`}>
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem className="text-destructive" onClick={() => onRevoke(a)}>
                          Revoke
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
