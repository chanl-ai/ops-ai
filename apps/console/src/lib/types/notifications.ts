export type NotificationKind = 'approval_waiting' | 'sla_at_risk' | 'publish_request' | 'mailbox_disconnected' | 'test_regression' | 'knowledge_change';

/** Other places the same notification went; an approval can be actioned from any of them. */
export type NotificationChannel = 'teams' | 'email';

export interface OpsNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  /** The record the notification is about. */
  href: string;
  createdAt: string;
  read: boolean;
  alsoSentTo: NotificationChannel[];
  /** Set when the item was already handled in another channel, e.g. approved in Teams. */
  handledElsewhere?: string;
}

/** The bell's feed for the current user and team, already split for display. */
export interface NotificationFeed {
  today: OpsNotification[];
  earlier: OpsNotification[];
  unread: number;
}
