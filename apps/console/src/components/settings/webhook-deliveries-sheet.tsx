'use client';

import * as React from 'react';
import { CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Clock, Inbox, RotateCw, SkipForward, XCircle } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { EmptyState } from '@/components/shared/empty-state';
import { JsonBlock } from '@/components/shared/json-block';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { plural, relativeTime } from '@/lib/format';
import type { ListResult } from '@/lib/types/query';
import type { DeliveryStatus, Webhook, WebhookDelivery } from '@/lib/types/settings';
import { cn } from '@/lib/utils';

const STATUS: Record<DeliveryStatus, { variant: 'default' | 'destructive' | 'outline' | 'secondary'; icon: typeof CheckCircle2; label: string }> = {
  success: { variant: 'secondary', icon: CheckCircle2, label: 'Delivered' },
  failed: { variant: 'destructive', icon: XCircle, label: 'Failed' },
  pending: { variant: 'outline', icon: Clock, label: 'Pending' },
  skipped: { variant: 'outline', icon: SkipForward, label: 'Skipped' },
};

function StatusBadge({ status }: { status: DeliveryStatus }) {
  const c = STATUS[status];
  return (
    <Badge variant={c.variant} className="gap-1 text-xs">
      <c.icon className="size-3" /> {c.label}
    </Badge>
  );
}

/** One delivery: event and status, then HTTP code, duration and attempts in fixed slots so rows align. Expands to the bodies. */
function DeliveryRow({ d, onResend, resending }: { d: WebhookDelivery; onResend?: (d: WebhookDelivery) => void; resending?: boolean }) {
  const [open, setOpen] = React.useState(false);
  const hasBody = !!(d.payload || d.responseBody);
  const resend = onResend && d.status === 'failed' && (
    <div className="flex justify-end border-t px-3 py-2">
      <LoadingButton size="sm" variant="outline" isLoading={resending} onClick={() => onResend(d)}>
        <RotateCw className="size-3.5" /> Resend
      </LoadingButton>
    </div>
  );
  const content = (
    <>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs">{d.event}</span>
        <StatusBadge status={d.status} />
      </div>
      <div className="flex items-center text-xs text-muted-foreground">
        <span className="w-[68px] shrink-0">{d.statusCode ? `HTTP ${d.statusCode}` : ' '}</span>
        <span className="w-[64px] shrink-0 text-right">{d.durationMs != null ? `${d.durationMs} ms` : ' '}</span>
        <span className="w-[84px] shrink-0 text-right">{plural(d.attempts, 'attempt')}</span>
        <span className="ml-auto shrink-0">{relativeTime(d.at)}</span>
      </div>
      {d.error && <p className="mt-1 truncate text-xs text-destructive">{d.error}</p>}
    </>
  );
  if (!hasBody)
    return (
      <div className="rounded-lg border text-sm">
        <div className="p-3">{content}</div>
        {resend}
      </div>
    );
  return (
    <div className="rounded-lg border text-sm">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="relative w-full rounded-lg p-3 pr-8 text-left transition-colors hover:bg-muted/50">
        {content}
        <ChevronDown className={cn('absolute top-3 right-3 size-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="space-y-2 border-t px-3 py-2">
          {d.payload && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Request body</p>
              <JsonBlock value={d.payload} maxHeight="12rem" />
            </div>
          )}
          {d.responseBody && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Response body</p>
              <JsonBlock value={d.responseBody} tone={d.status === 'failed' ? 'error' : 'default'} maxHeight="12rem" />
            </div>
          )}
        </div>
      )}
      {resend}
    </div>
  );
}

/**
 * Delivery history for one webhook, adapted from the shared component library's webhook deliveries sheet: status filter,
 * expandable rows with request and response bodies, paged from the server.
 */
export function WebhookDeliveriesSheet({
  webhook,
  result,
  isPending,
  isError,
  onRetry,
  onResend,
  resendingId,
  status,
  onStatusChange,
  page,
  onPageChange,
  navigation,
  footerActions,
  onOpenChange,
}: {
  webhook: Webhook | null;
  result?: ListResult<WebhookDelivery>;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  /** Absent while the webhook is paused. */
  onResend?: (d: WebhookDelivery) => void;
  resendingId?: string;
  status: string;
  onStatusChange: (s: string) => void;
  page: number;
  onPageChange: (p: number) => void;
  navigation?: DetailSheetNavigation;
  footerActions?: React.ReactNode;
  onOpenChange: (open: boolean) => void;
}) {
  const deliveries = result?.data ?? [];
  const pg = result?.pagination;
  return (
    <DetailSheet
      open={!!webhook}
      onOpenChange={onOpenChange}
      navigation={navigation}
      scrollKey={`${webhook?.id}-${page}-${status}`}
      widthClass="sm:max-w-xl"
      testId="webhook-deliveries-sheet"
      title={webhook?.name ?? 'Webhook'}
      description={webhook && <span className="font-mono break-all">{webhook.url}</span>}
      tags={webhook && webhook.events.map((e) => <Badge key={e} variant="outline" className="font-mono text-[11px] font-normal">{e}</Badge>)}
      footerActions={footerActions}
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Select value={status} onValueChange={onStatusChange}>
            <SelectTrigger className="w-[160px]" aria-label="Delivery status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {(Object.keys(STATUS) as DeliveryStatus[]).map((s) => (
                <SelectItem key={s} value={s}>
                  {STATUS[s].label}
                  {result?.facets.status?.[s] != null && <span className="text-muted-foreground">· {result.facets.status[s]}</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {pg && <span className="ml-auto text-xs text-muted-foreground">{plural(pg.total, 'delivery', 'deliveries')}</span>}
        </div>

        {isPending && !result ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : isError && !result ? (
          <QueryError what="deliveries" onRetry={onRetry} />
        ) : deliveries.length === 0 ? (
          <EmptyState icon={Inbox} title={status === 'all' ? 'No deliveries yet' : 'No deliveries with this status'} description={status === 'all' ? 'Deliveries appear here when one of its events happens.' : 'Pick another status to see more.'} />
        ) : (
          <div className="space-y-2">
            {deliveries.map((d) => (
              <DeliveryRow key={d.id} d={d} onResend={onResend} resending={resendingId === d.id} />
            ))}
          </div>
        )}

        {pg && pg.totalPages > 1 && (
          <div className="flex items-center justify-between pt-1">
            <Button variant="outline" size="sm" disabled={!pg.hasPrev} onClick={() => onPageChange(page - 1)} aria-label="Previous page">
              <ChevronLeft className="size-4" />
            </Button>
            <span className="text-xs text-muted-foreground">
              Page {pg.page} of {pg.totalPages}
            </span>
            <Button variant="outline" size="sm" disabled={!pg.hasNext} onClick={() => onPageChange(page + 1)} aria-label="Next page">
              <ChevronRight className="size-4" />
            </Button>
          </div>
        )}
      </div>
    </DetailSheet>
  );
}
