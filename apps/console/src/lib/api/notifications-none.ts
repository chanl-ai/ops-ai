import type { NotificationFeed } from '@/lib/types/notifications';

import type { NotificationsApi } from './notifications-contract';

const EMPTY: NotificationFeed = { today: [], earlier: [], unread: 0 };

/**
 * The feed while no service owns notifications yet. Any area on a real service means the console is not on the
 * mock, so the bell stays empty and raises no toasts; a seeded mock item there would read as real work and can
 * cover controls under test.
 */
export function createNoNotifications(): NotificationsApi {
  return {
    list: async () => EMPTY,
    markRead: async () => EMPTY,
    markAllRead: async () => EMPTY,
  };
}
