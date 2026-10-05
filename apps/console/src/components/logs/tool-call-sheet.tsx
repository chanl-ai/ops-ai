'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { EyeOff, ShieldCheck } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { JsonBlock } from '@/components/shared/json-block';
import { QueryError } from '@/components/shared/query-states';
import { KeyValues, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { count, dateTime, ms } from '@/lib/format';
import type { ToolCallDetail, ToolCallRow } from '@/lib/types/governance';

import { ApprovalCell, cad, CallStatusText, GATEWAY_LABEL, OperationBadge } from './log-meta';

/**
 * One gateway call: who made it, what it touched, how it was authorised and what went over the wire.
 * Adapted from the shared component library's session event card: request and response as
 * JSON blocks, with the masked fields listed so a reader knows what the log does not hold.
 */
export function ToolCallSheet({
  row,
  call,
  isPending,
  isError,
  onRetry,
  navigation,
  onOpenChange,
}: {
  row: ToolCallRow | null;
  call?: ToolCallDetail;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  navigation?: DetailSheetNavigation;
  onOpenChange: (open: boolean) => void;
}) {
  const c = call ?? row;
  return (
    <DetailSheet
      open={!!row}
      onOpenChange={onOpenChange}
      navigation={navigation}
      scrollKey={row?.id}
      testId="tool-call-sheet"
      title={c ? <code className="font-mono text-base">{c.target}</code> : 'Call'}
      description={c ? `${dateTime(c.at)} · ${GATEWAY_LABEL[c.gateway]} · ${c.system}` : undefined}
      tags={
        c && (
          <>
            <CallStatusText status={c.status} />
            <OperationBadge operation={c.operation} />
            {c.record && <Badge variant="outline" className="font-normal">{c.record}</Badge>}
          </>
        )
      }
    >
      {!c ? null : (
        <div className="flex flex-col gap-4">
          <Section title="Call" flush bodyClassName="px-4">
            <KeyValues
              rows={[
                ['Workflow', <Link key="w" href={`/workflows/${c.workflowId}`} className="underline-offset-4 hover:underline">{c.workflowName}</Link>],
                ['Agent', c.agentName],
                ['Run', <Link key="r" href={`/workflows/${c.workflowId}?tab=runs`} className="font-mono text-xs underline-offset-4 hover:underline">{c.runId}</Link>],
                ...(c.caseId ? ([['Case', <Link key="c" href={`/cases/${c.caseId}`} className="font-mono text-xs underline-offset-4 hover:underline">{c.caseId}</Link>]] as [string, ReactNode][]) : []),
                ['Identity', call ? <code key="i" className="font-mono text-xs">{call.identity}</code> : undefined],
                ['Latency', ms(c.latencyMs)],
                ...(c.tokens ? ([['Tokens', `${count(c.tokens.input)} in · ${count(c.tokens.output)} out`], ['Cost', c.cost != null ? cad(c.cost) : undefined]] as [string, ReactNode][]) : []),
                ['Request id', call ? <code key="q" className="font-mono text-xs">{call.requestId}</code> : undefined],
              ]}
            />
          </Section>

          <Section title="Approval and policy" flush bodyClassName="px-4">
            <KeyValues
              rows={[
                ['Approval', <ApprovalCell key="a" approval={c.approval} />],
                ...(c.approval.tokenId ? ([['Token', <code key="t" className="font-mono text-xs">{c.approval.tokenId}</code>]] as [string, ReactNode][]) : []),
                ...(c.approval.at ? ([['Approved at', dateTime(c.approval.at)]] as [string, ReactNode][]) : []),
                ...(c.approval.reviewId ? ([['Review', <Link key="rv" href={`/reviews?review=${c.approval.reviewId}`} className="underline-offset-4 hover:underline">{c.approval.reviewId}</Link>]] as [string, ReactNode][]) : []),
                [
                  'Policy',
                  call?.policy ? (
                    <span key="p" className="inline-flex flex-col gap-0.5">
                      <span className="inline-flex items-center gap-1">
                        <ShieldCheck className="size-3.5 text-muted-foreground" /> {call.policy.name} · version {call.policy.version}
                      </span>
                      <code className="font-mono text-xs text-muted-foreground">{call.policy.rule}</code>
                    </span>
                  ) : undefined,
                ],
              ]}
            />
          </Section>

          {isPending && !call ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-28 w-full" />
            </div>
          ) : isError && !call ? (
            <QueryError what="this call" onRetry={onRetry} />
          ) : call ? (
            <>
              {call.error && (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">Error</div>
                  <JsonBlock value={{ error: call.error }} tone="error" />
                </div>
              )}
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">Request</div>
                <JsonBlock value={call.request} />
              </div>
              {!call.error && (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">Response</div>
                  <JsonBlock value={call.response} />
                </div>
              )}
              {call.redacted.length > 0 && (
                <div className="flex items-start gap-2 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
                  <EyeOff className="mt-0.5 size-3.5 shrink-0" />
                  <div>
                    Masked before storage, shown as <code className="font-mono">[redacted]</code>:{' '}
                    {call.redacted.map((f, i) => (
                      <span key={f}>
                        {i > 0 && ', '}
                        <code className="font-mono text-foreground">{f}</code>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </DetailSheet>
  );
}
