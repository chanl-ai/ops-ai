import type { NotificationFeed } from '@/lib/types/notifications';

/** The current user's notifications for the current team. */
export interface NotificationsApi {
  list(): Promise<NotificationFeed>;
  markRead(ids: string[]): Promise<NotificationFeed>;
  markAllRead(): Promise<NotificationFeed>;
}
