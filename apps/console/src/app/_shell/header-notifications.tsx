'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { NotificationsBell } from '@/components/header/notifications-bell';
import { useMarkNotificationsRead, useNotifications } from '@/hooks/notification-queries';
import type { OpsNotification } from '@/lib/types/notifications';

/** The bell, wired to the feed. A notification that arrives after the first load is also shown as a toast. */
export function HeaderNotifications() {
  const router = useRouter();
  const feed = useNotifications();
  const mark = useMarkNotificationsRead();
  const seen = React.useRef<Set<string> | null>(null);

  React.useEffect(() => {
    if (!feed.data) return;
    const all = [...feed.data.today, ...feed.data.earlier];
    if (seen.current) {
      for (const n of all.filter((x) => !x.read && !seen.current!.has(x.id)))
        toast(n.title, { description: n.body, action: { label: 'Open', onClick: () => open(n) } });
    }
    seen.current = new Set(all.map((n) => n.id));
  }, [feed.data]);

  const fail = (e: Error) => toast.error('Couldn’t update notifications', { description: e.message });
  function open(n: OpsNotification) {
    if (!n.read) mark.mutate([n.id], { onError: fail });
    router.push(n.href);
  }

  return (
    <NotificationsBell
      feed={feed.data}
      loading={feed.isPending}
      error={feed.isError ? feed.error.message : undefined}
      onRetry={() => feed.refetch()}
      onOpen={open}
      onMarkRead={(id) => mark.mutate([id], { onError: fail })}
      onMarkAllRead={() => mark.mutate('all', { onError: fail })}
      settingsHref="/settings/notifications"
    />
  );
}
