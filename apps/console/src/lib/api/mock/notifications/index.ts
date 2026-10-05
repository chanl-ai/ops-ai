import type { Review } from '@/lib/types/domain';
import type { NotificationFeed, OpsNotification } from '@/lib/types/notifications';

import type { NotificationsApi } from '../../notifications-contract';
import { respond } from '../runtime';
import { inTeam } from '../teams';
import { LIVE_TEMPLATES, NOTIFICATION_SEEDS, type NotificationSeed } from './seed';

/** How often a new notification arrives while the app is polling. */
const PUSH_EVERY_MS = 45_000;
/** Read state survives a reload within the browser session, as a real feed would. */
const READ_KEY = 'ops-mock-notifications-read';

function loadRead(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(READ_KEY) ?? '[]') as string[]);
  } catch {
    return new Set();
  }
}

function saveRead(ids: Iterable<string>) {
  try {
    sessionStorage.setItem(READ_KEY, JSON.stringify([...ids]));
  } catch {
    // Storage blocked (private window, preview): read state lasts for this page only.
  }
}

interface Deps {
  me: string;
  reviews: () => Review[];
}

/**
 * The bell's feed. New notifications are pushed lazily: a list call made at least 45 s after the last push adds
 * the next template the current team can see, so an open tab gets one roughly every 45 s and a closed one none.
 */
export function createNotificationsMock(deps: Deps): NotificationsApi {
  const created = Date.now();
  const readIds = loadRead();
  const rows: (OpsNotification & { owner: string })[] = NOTIFICATION_SEEDS.map(({ minutesAgo, ...n }: NotificationSeed) => ({ ...n, read: n.read || readIds.has(n.id), createdAt: new Date(created - minutesAgo * 60_000).toISOString() }));
  const markRead = (n: OpsNotification) => {
    n.read = true;
    readIds.add(n.id);
  };
  let lastPush = created;
  let next = 0;

  const visible = () => rows.filter((n) => n.owner === deps.me || inTeam(n.owner));
  const href = (n: OpsNotification) => {
    if (n.kind !== 'publish_request') return n.href;
    const r = deps.reviews().find((x) => x.kind === 'publish_request' && x.workflowId === 'wf_dispute');
    return r ? `/reviews?review=${r.id}` : n.href;
  };

  function push() {
    if (Date.now() - lastPush < PUSH_EVERY_MS) return;
    lastPush = Date.now();
    for (let i = 0; i < LIVE_TEMPLATES.length; i++) {
      const t = LIVE_TEMPLATES[(next + i) % LIVE_TEMPLATES.length];
      if (t.owner !== deps.me && !inTeam(t.owner)) continue;
      next = (next + i + 1) % LIVE_TEMPLATES.length;
      rows.unshift({ ...t, id: `ntf_live_${Date.now().toString(36)}`, read: false, createdAt: new Date().toISOString() });
      return;
    }
  }

  const feed = (empty: boolean): NotificationFeed => {
    const items = empty ? [] : visible().sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    const today = new Date().toDateString();
    const out = items.map(({ owner: _owner, ...n }) => ({ ...n, href: href(n) }));
    return {
      today: out.filter((n) => new Date(n.createdAt).toDateString() === today),
      earlier: out.filter((n) => new Date(n.createdAt).toDateString() !== today),
      unread: out.filter((n) => !n.read).length,
    };
  };

  return {
    list: () =>
      respond((m) => {
        push();
        return feed(m === 'empty');
      }),
    markRead: (ids) =>
      respond((m) => {
        for (const n of rows) if (ids.includes(n.id)) markRead(n);
        saveRead(readIds);
        return feed(m === 'empty');
      }),
    markAllRead: () =>
      respond((m) => {
        for (const n of visible()) markRead(n);
        saveRead(readIds);
        return feed(m === 'empty');
      }),
  };
}
