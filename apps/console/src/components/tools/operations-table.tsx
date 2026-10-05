'use client';

import { Lock, UserCheck, Users } from 'lucide-react';

import { StopRowClick } from '@/components/shared/form-field';
import { AccessBadge } from '@/components/status-badges';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count } from '@/lib/format';
import type { ModuleOperation } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

import { BindingText, errorTone, pctText } from './module-meta';

/** How a call to this operation is supervised, in one line. */
export function SupervisionText({ op }: { op: Pick<ModuleOperation, 'access' | 'requiresApproval' | 'fourEyes'> }) {
  if (op.fourEyes)
    return (
      <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-red-700 dark:text-red-400">
        <Users className="size-3.5" /> Four eyes
      </span>
    );
  if (op.access === 'read') return <span className="text-xs text-muted-foreground">None</span>;
  return op.requiresApproval ? (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-amber-700 dark:text-amber-400">
      <UserCheck className="size-3.5" /> Every call
    </span>
  ) : (
    <span className="text-xs whitespace-nowrap text-muted-foreground">Gate policy only</span>
  );
}

/** The module's operations; a row opens the operation sheet, the switch exposes or hides it (a staged change). */
export function OperationsTable({ operations, onOpen, onToggle, toggling }: { operations: ModuleOperation[]; onOpen: (op: ModuleOperation) => void; onToggle: (op: ModuleOperation, enabled: boolean) => void; toggling: boolean }) {
  return (
    <div className="overflow-x-auto rounded-md border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Operation</TableHead>
            <TableHead>Access</TableHead>
            <TableHead>Record binding</TableHead>
            <TableHead>Approval · limit</TableHead>
            <TableHead className="text-right">Workflows</TableHead>
            <TableHead className="text-right">Calls · 24h</TableHead>
            <TableHead>Exposed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {operations.map((o) => (
            <TableRow key={o.id} className="cursor-pointer" onClick={() => onOpen(o)}>
              <TableCell className={cn('w-72 max-w-72', !o.enabled && 'opacity-60')} title={`${o.name}: ${o.description}${o.method ? ` (${o.method} ${o.path})` : ''}`}>
                <code className="block truncate font-mono text-[13px] font-medium">{o.name}</code>
                <div className="truncate text-xs text-muted-foreground">{o.description}</div>
                {o.method && (
                  <div className="truncate font-mono text-[11px] text-muted-foreground">
                    {o.method} {o.path}
                  </div>
                )}
                {!o.enabled && <div className="text-xs text-muted-foreground">Hidden: calls are refused</div>}
              </TableCell>
              <TableCell>
                <AccessBadge access={o.access} />
              </TableCell>
              <TableCell>
                {o.binding ? (
                  <span className="inline-flex items-center gap-1">
                    <Lock className="size-3 text-muted-foreground" />
                    <BindingText binding={o.binding} />
                  </span>
                ) : (
                  <BindingText binding={null} />
                )}
              </TableCell>
              <TableCell>
                <SupervisionText op={o} />
                <div className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                  {o.rateLimitPerMin} a minute{o.amountMax ? ` · up to $${count(o.amountMax)}` : ''}
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{o.approvedWorkflows}</TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {count(o.calls24h)}
                <div className={cn('text-xs', o.calls24h ? errorTone(o.errorRate) : 'text-muted-foreground')}>{o.calls24h ? `${pctText(o.errorRate)} errors` : 'No calls'}</div>
              </TableCell>
              <TableCell>
                <StopRowClick align="start">
                  <Switch checked={o.enabled} disabled={toggling} onCheckedChange={(v) => onToggle(o, v)} aria-label={`${o.enabled ? 'Hide' : 'Expose'} ${o.name}`} />
                </StopRowClick>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
