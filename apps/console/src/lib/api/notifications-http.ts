import type { NotificationsApi } from './notifications-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the notification bell; `get` and `send` come from the main HTTP client. */
export function createNotificationsHttp(get: Get, send: Send): NotificationsApi {
  return {
    list: () => get('/notifications'),
    markRead: (ids) => send('POST', '/notifications/read', { ids }),
    markAllRead: () => send('POST', '/notifications/read-all'),
  };
}
