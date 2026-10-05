'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { NotificationFeed } from '@/lib/types/notifications';

const KEY = ['notifications'] as const;
/** The bell polls while the tab is visible; the backend pushes new items between polls. */
const POLL_MS = 15_000;

export const useNotifications = () => useQuery({ queryKey: KEY, queryFn: api.notifications.list, refetchInterval: POLL_MS });

/** Marks read and writes the returned feed straight into the cache, so the badge drops without a refetch. */
export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[] | 'all') => (ids === 'all' ? api.notifications.markAllRead() : api.notifications.markRead(ids)),
    onSuccess: (feed: NotificationFeed) => qc.setQueryData(KEY, feed),
  });
}
