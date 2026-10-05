'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertCircle, AlertTriangle, Bell, BookOpenCheck, Check, CheckCheck, FlaskConical, Mail, MailWarning, MessageSquare, Rocket, Settings, UserCheck, type LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { relativeTime } from '@/lib/format';
import type { NotificationChannel, NotificationFeed, NotificationKind, OpsNotification } from '@/lib/types/notifications';
import { cn } from '@/lib/utils';

const KIND: Record<NotificationKind, { icon: LucideIcon; tone: string }> = {
  approval_waiting: { icon: UserCheck, tone: 'bg-primary/10 text-primary' },
  sla_at_risk: { icon: AlertTriangle, tone: 'bg-amber-500/10 text-amber-600 dark:text-amber-400' },
  publish_request: { icon: Rocket, tone: 'bg-sky-500/10 text-sky-600 dark:text-sky-400' },
  mailbox_disconnected: { icon: MailWarning, tone: 'bg-destructive/10 text-destructive' },
  test_regression: { icon: FlaskConical, tone: 'bg-destructive/10 text-destructive' },
  knowledge_change: { icon: BookOpenCheck, tone: 'bg-violet-500/10 text-violet-600 dark:text-violet-400' },
};

const CHANNEL: Record<NotificationChannel, { label: string; icon: LucideIcon }> = {
  teams: { label: 'Teams', icon: MessageSquare },
  email: { label: 'Email', icon: Mail },
};

/**
 * Top-bar bell. Adapted from the shared component library's notification bell (badge, popover card, settings link, mark
 * all read), grouped Today / Earlier, with per-item mark read and the other channels each item went to.
 */
export function NotificationsBell({
  feed,
  loading,
  error,
  onRetry,
  onOpen,
  onMarkRead,
  onMarkAllRead,
  settingsHref,
}: {
  feed?: NotificationFeed;
  loading: boolean;
  error?: string;
  onRetry: () => void;
  onOpen: (n: OpsNotification) => void;
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  settingsHref: string;
}) {
  const [open, setOpen] = React.useState(false);
  const unread = feed?.unread ?? 0;
  const empty = feed && !feed.today.length && !feed.earlier.length;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative size-8" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} data-testid="header-notifications">
          <Bell className="size-4" />
          {unread > 0 && (
            <Badge variant="destructive" className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center px-1 py-0 text-[10px] tabular-nums">
              {unread > 9 ? '9+' : unread}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[400px] max-w-[calc(100vw-2rem)] overflow-hidden p-0" align="end" collisionPadding={12}>
        <div className="flex items-center justify-between gap-2 border-b bg-muted/50 px-4 py-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold">Notifications</h3>
            <p className="text-xs text-muted-foreground">{!feed ? (error ? 'Not loaded' : 'Loading…') : unread ? `${unread} unread` : 'You’re all caught up'}</p>
          </div>
          <div className="flex items-center gap-1">
            {unread > 0 && (
              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onMarkAllRead}>
                <CheckCheck className="size-3.5" /> Mark all read
              </Button>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button asChild variant="ghost" size="icon" className="size-7" onClick={() => setOpen(false)}>
                  <Link href={settingsHref} aria-label="Notification settings">
                    <Settings className="size-4" />
                  </Link>
                </Button>
              </TooltipTrigger>
              <TooltipContent>Notification settings</TooltipContent>
            </Tooltip>
          </div>
        </div>

        <div className="max-h-[min(70vh,440px)] overflow-y-auto">
          {loading && !feed ? (
            <div className="flex flex-col gap-4 p-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex gap-3">
                  <Skeleton className="size-8 shrink-0 rounded-full" />
                  <div className="flex flex-1 flex-col gap-2">
                    <Skeleton className="h-4 w-48" />
                    <Skeleton className="h-3 w-full" />
                  </div>
                </div>
              ))}
            </div>
          ) : error && !feed ? (
            <div className="flex flex-col items-center gap-2 px-6 py-8 text-center text-sm">
              <AlertCircle className="size-6 text-destructive" />
              <p className="text-muted-foreground">Couldn’t load notifications.</p>
              <Button size="sm" variant="outline" onClick={onRetry}>
                Try again
              </Button>
            </div>
          ) : empty ? (
            <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
              <Bell className="size-8 text-muted-foreground/60" />
              <p className="text-sm font-medium">No notifications</p>
              <p className="text-xs text-muted-foreground">Approvals waiting for you, SLA warnings and publish requests appear here.</p>
            </div>
          ) : (
            feed && (
              <>
                <Section label="Today" items={feed.today} onOpen={(n) => {
                    setOpen(false);
                    onOpen(n);
                  }} onMarkRead={onMarkRead} />
                <Section label="Earlier" items={feed.earlier} onOpen={(n) => {
                    setOpen(false);
                    onOpen(n);
                  }} onMarkRead={onMarkRead} />
              </>
            )
          )}
        </div>

        <div className="border-t bg-muted/50 px-4 py-2 text-xs">
          <Link href={settingsHref} className="text-muted-foreground hover:text-foreground hover:underline" onClick={() => setOpen(false)}>
            Notification settings
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Section({ label, items, onOpen, onMarkRead }: { label: string; items: OpsNotification[]; onOpen: (n: OpsNotification) => void; onMarkRead: (id: string) => void }) {
  if (!items.length) return null;
  return (
    <section aria-label={label}>
      <h4 className="sticky top-0 z-10 border-b bg-popover px-4 py-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</h4>
      <ul className="divide-y">
        {items.map((n) => (
          <Item key={n.id} n={n} onOpen={() => onOpen(n)} onMarkRead={() => onMarkRead(n.id)} />
        ))}
      </ul>
    </section>
  );
}

function Item({ n, onOpen, onMarkRead }: { n: OpsNotification; onOpen: () => void; onMarkRead: () => void }) {
  const K = KIND[n.kind];
  return (
    <li className={cn('group relative flex gap-3 px-4 py-3 hover:bg-muted/50', !n.read && 'bg-primary/[0.03]')}>
      <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', K.tone)}>
        <K.icon className="size-4" />
      </span>
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left after:absolute after:inset-0 focus-visible:outline-none" data-testid={`notification-${n.id}`}>
        <span className="flex items-start gap-2">
          <span className={cn('min-w-0 flex-1 text-sm leading-snug', !n.read && 'font-semibold')}>{n.title}</span>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{relativeTime(n.createdAt)}</span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{n.body}</span>
        {(n.alsoSentTo.length > 0 || n.handledElsewhere) && (
          <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {n.handledElsewhere && (
              <Badge variant="outline" className="border-emerald-600/40 bg-emerald-500/10 font-normal text-emerald-700 dark:text-emerald-400">
                <Check className="size-3" /> {n.handledElsewhere}
              </Badge>
            )}
            {n.alsoSentTo.map((c) => {
              const C = CHANNEL[c];
              return (
                <span key={c} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  <C.icon className="size-3" /> Also sent to {C.label}
                </span>
              );
            })}
          </span>
        )}
      </button>
      {!n.read && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" className="relative z-10 size-6 shrink-0 self-center" onClick={onMarkRead} aria-label={`Mark “${n.title}” as read`}>
              <span className="size-2 rounded-full bg-primary group-hover:hidden" aria-hidden />
              <Check className="hidden size-3.5 group-hover:block" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Mark as read</TooltipContent>
        </Tooltip>
      )}
    </li>
  );
}
