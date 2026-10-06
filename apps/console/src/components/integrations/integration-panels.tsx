'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowUpRight, CheckCircle2, CircleX, History, Link2Off, Plus, ScrollText, Zap } from 'lucide-react';

import { ActionBadge } from '@/components/logs/log-meta';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateTime, plural, relativeTime, shortDate } from '@/lib/format';
import type { DependantType, IntegrationDetail } from '@/lib/types/integrations';
import { cn } from '@/lib/utils';

import { TONE_TEXT } from './integration-meta';
import { impactSentence } from './revoke-dialog';

const TYPE_LABEL: Record<DependantType, string> = { source: 'Knowledge source', tool_module: 'Tool module', mailbox: 'Mailbox' };

/** Last error with the action that clears it, then the health check history. */
export function OverviewPanel({ i, onFix, fixing, onRecheck, rechecking }: { i: IntegrationDetail; onFix: () => void; fixing: boolean; onRecheck: () => void; rechecking: boolean }) {
  const failing = i.checks.filter((c) => !c.ok).length;
  return (
    <div className="flex flex-col gap-4">
      {i.lastError && i.fix ? (
        <Alert variant="destructive" data-testid="last-error">
          <AlertTriangle className="size-4" />
          <AlertTitle>{i.status === 'revoked' ? 'Revoked' : i.status === 'needs_reconnect' ? 'Needs reconnecting' : 'Failing'}</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <p>{i.lastError}</p>
            <LoadingButton size="sm" variant="outline" className="border-destructive/40 text-foreground" isLoading={fixing} onClick={onFix}>
              {i.fix.label}
            </LoadingButton>
          </AlertDescription>
        </Alert>
      ) : i.status === 'expiring' ? (
        <Alert>
          <AlertTriangle className="size-4" />
          <AlertTitle>Expires in {plural(Math.max(0, Math.round((new Date(i.expiresAt ?? 0).getTime() - Date.now()) / 86_400_000)), 'day')} on {shortDate(i.expiresAt)}</AlertTitle>
          <AlertDescription>Renew before then, or {plural(i.usedBy.sources + i.usedBy.modules + i.usedBy.mailboxes, 'dependant')} stop when it lapses.</AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <CheckCircle2 className="size-4 text-emerald-600" />
          <AlertTitle>Signing in and answering</AlertTitle>
          <AlertDescription>The last check issued a token and a read call answered.</AlertDescription>
        </Alert>
      )}
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">
          Health checks <span className="font-normal text-muted-foreground">· every 6 hours{failing ? ` · ${failing} failed` : ''}</span>
        </h3>
        <LoadingButton size="sm" variant="outline" isLoading={rechecking} onClick={onRecheck} disabled={i.status === 'revoked'}>
          Re-check now
        </LoadingButton>
      </div>
      <div className="overflow-x-auto rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Result</TableHead>
              <TableHead>When</TableHead>
              <TableHead>Latency</TableHead>
              <TableHead>Detail</TableHead>
              <TableHead>By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {i.checks.map((c) => (
              <TableRow key={c.id}>
                <TableCell>{c.ok ? <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400"><CheckCircle2 className="size-3.5" /> Passed</span> : <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600 dark:text-red-400"><CircleX className="size-3.5" /> Failed</span>}</TableCell>
                <TableCell className="text-xs whitespace-nowrap text-muted-foreground" title={dateTime(c.at)}>{relativeTime(c.at)}</TableCell>
                <TableCell className="text-xs tabular-nums">{c.latencyMs} ms</TableCell>
                <TableCell className="max-w-96 truncate text-sm" title={c.message}>{c.message}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{c.by}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/** Granted against what the system offers, and open requests for more. */
export function ScopesPanel({ i, onRequest }: { i: IntegrationDetail; onRequest: () => void }) {
  const pending = i.scopeRequests.find((r) => r.status === 'pending');
  const label = (sid: string) => i.availableScopes.find((s) => s.id === sid)?.label ?? sid;
  const notGranted = i.availableScopes.filter((s) => !i.scopes.includes(s.id));
  return (
    <div className="flex flex-col gap-4">
      {pending && (
        <Alert data-testid="scope-request-pending">
          <History className="size-4" />
          <AlertTitle>
            {plural(pending.scopes.length, 'scope')} requested, waiting for {pending.approver}
          </AlertTitle>
          <AlertDescription>
            {pending.scopes.map(label).join(', ')} · asked by {pending.requestedBy} {relativeTime(pending.requestedAt)}: “{pending.justification}”. Nothing changes until {pending.approver} approves.
          </AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {i.scopes.length} of {i.availableScopes.length} granted. Requests go to {i.systemOwner}, who owns {i.name.split(' · ')[0]}.
        </p>
        <Button size="sm" variant="outline" onClick={onRequest} disabled={!!pending || !notGranted.length || i.status === 'revoked'}>
          <Plus className="size-4" /> Request more scopes
        </Button>
      </div>
      <div className="overflow-x-auto rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Scope</TableHead>
              <TableHead>Access</TableHead>
              <TableHead>What it allows</TableHead>
              <TableHead>State</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {i.availableScopes.map((s) => {
              const granted = i.scopes.includes(s.id);
              const requested = pending?.scopes.includes(s.id);
              return (
                <TableRow key={s.id} className={cn(!granted && !requested && 'text-muted-foreground')}>
                  <TableCell>
                    <span className="font-medium">{s.label}</span>
                    <code className="block font-mono text-[11px] text-muted-foreground">{s.id}</code>
                  </TableCell>
                  <TableCell className="text-xs">{s.access === 'write' ? 'Write' : 'Read'}</TableCell>
                  <TableCell className="max-w-96 text-sm whitespace-normal">{s.description}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap">
                    {granted ? <span className="text-emerald-700 dark:text-emerald-400">Granted</span> : requested ? <span className="text-amber-700 dark:text-amber-400">Requested</span> : 'Not granted'}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/** Sources, tool modules and mailboxes on this connection, and what a revoke would stop. */
export function UsedByPanel({ i, onRevoke }: { i: IntegrationDetail; onRevoke: () => void }) {
  if (!i.dependants.length) return <EmptyState icon={Link2Off} title="Nothing uses this connection" description="Pick it when adding a knowledge source, a tool module or a mailbox." />;
  const impact = { dependants: i.dependants, sources: i.usedBy.sources, modules: i.usedBy.modules, mailboxes: i.usedBy.mailboxes };
  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Used by</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>If revoked</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {i.dependants.map((d) => (
              <TableRow key={`${d.type}-${d.id}`}>
                <TableCell>
                  <Link href={d.href} className="font-medium hover:underline">
                    {d.name}
                  </Link>
                </TableCell>
                <TableCell className="text-xs whitespace-nowrap text-muted-foreground">{TYPE_LABEL[d.type]}</TableCell>
                <TableCell className="text-sm whitespace-nowrap">{d.owner}</TableCell>
                <TableCell className={cn('text-xs whitespace-nowrap', TONE_TEXT[d.tone])}>{d.status}</TableCell>
                <TableCell className="max-w-80 text-xs whitespace-normal text-muted-foreground">{d.stops}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {i.status !== 'revoked' && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm" data-testid="revoke-preview">
          <span>
            <span className="font-medium">Revoke impact: </span>
            {impactSentence(impact)}
          </span>
          <Button size="sm" variant="outline" className="border-destructive/40" onClick={onRevoke}>
            Revoke…
          </Button>
        </div>
      )}
    </div>
  );
}

/** Recent syncs and gateway calls through this connection. */
export function ActivityPanel({ i }: { i: IntegrationDetail }) {
  if (!i.activity.length) return <EmptyState icon={Zap} title="No activity yet" description="Syncs and calls through this connection show here." />;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3 text-sm">
        <Link href="/logs/tool-calls" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
          All tool calls <ArrowUpRight className="size-3.5" />
        </Link>
        <Link href="/sources" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
          All sources <ArrowUpRight className="size-3.5" />
        </Link>
      </div>
      <ul className="divide-y rounded-md border bg-card">
        {i.activity.map((a) => (
          <li key={a.id}>
            <Link href={a.href} className="flex items-center gap-3 px-3 py-2.5 hover:bg-muted/50">
              {a.ok ? <CheckCircle2 className="size-4 shrink-0 text-emerald-600" /> : <CircleX className="size-4 shrink-0 text-red-600" />}
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-medium">
                  {a.kind === 'call' ? <code className="font-mono text-[13px]">{a.label}</code> : a.label}
                  <span className="text-xs font-normal text-muted-foreground">{a.kind === 'call' ? 'Tool call' : 'Sync'}</span>
                </span>
                <span className="block truncate text-xs text-muted-foreground">{a.detail}</span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground" title={dateTime(a.at)}>
                {relativeTime(a.at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Audit entries for this connection: connects, revokes, rotations and scope requests. */
export function AuditPanel({ i }: { i: IntegrationDetail }) {
  if (!i.audit.length) return <EmptyState icon={ScrollText} title="No audit entries yet" description="Connecting, revoking, rotating and scope changes are recorded here." />;
  return (
    <div className="flex flex-col gap-3">
      <Link href="/logs/audit" className="inline-flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground">
        Full audit log <ArrowUpRight className="size-3.5" />
      </Link>
      <ul className="divide-y rounded-md border bg-card" data-testid="integration-audit">
        {i.audit.map((e) => (
          <li key={e.id} className="flex flex-col gap-1 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <ActionBadge action={e.action} />
              <span className="font-medium">{e.summary}</span>
              <span className="ml-auto text-xs text-muted-foreground" title={dateTime(e.at)}>
                {e.actor.name} · {relativeTime(e.at)}
              </span>
            </div>
            {e.diff.length > 0 && (
              <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                {e.diff.map((d) => (
                  <span key={d.field} className="break-all">
                    {d.field}: {d.before && <span className="line-through">{d.before}</span>} {d.before && '→ '}
                    <span className="text-foreground">{d.after}</span>
                  </span>
                ))}
              </div>
            )}
            {e.reason && <span className="text-xs text-muted-foreground">Reason: {e.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
