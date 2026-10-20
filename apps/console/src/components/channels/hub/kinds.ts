import { Code, Hash, Mail, MessagesSquare, Plug, Users, type LucideIcon } from 'lucide-react';

import type { ChannelHealth, ChannelType } from '@/lib/types/channels';

/** What each kind of channel is, for the gallery, the tabs and a kind's landing (docs/console/approved/channels). */
export interface KindInfo {
  type: ChannelType;
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  includes: string[];
}

export const KINDS: KindInfo[] = [
  { type: 'email', title: 'Email mailbox', href: '/channels/email', icon: Mail, description: 'A new email in a watched folder starts a workflow; replies go out through a sender you choose.', includes: ['Each new email in a watched folder starts the workflow it serves', 'Attachments land in Files, linked from the run', 'Replies go out through the sender the mailbox names', 'Sign-in secrets come from the Secrets list, never typed here'] },
  { type: 'chat', title: 'Chat embed', href: '/channels/chat', icon: MessagesSquare, description: 'An agent’s chat on one of the bank’s own pages, following its latest version or pinned to one.', includes: ['An agent’s chat on the bank’s own pages, signed in with the person’s SSO', 'Follows the latest published version, or pinned to one', 'Sites allowed, mint keys and 7-day usage per embed', 'Pause or retire an embed without touching the agent'] },
  { type: 'api', title: 'API', href: '/channels/api', icon: Code, description: 'The bank’s systems start runs with an API key and read what happened.', includes: ['The bank’s systems start runs with an API key', 'Each key acts for its team', 'Revoke a key at once'] },
  { type: 'mcp', title: 'MCP', href: '/channels/mcp', icon: Plug, description: 'Offer a published workflow as a tool to assistants that speak MCP.', includes: ['Offer a published workflow as a tool to assistants', 'Each person signs in with their own account', 'Calls held for approval wait in Human Tasks'] },
  { type: 'slack', title: 'Slack', href: '/channels/slack', icon: Hash, description: 'People ask an agent in a channel or a direct message and get the answer in the thread.', includes: ['Ask an agent in a channel or a direct message', 'The answer comes back in the thread'] },
  { type: 'teams', title: 'Teams', href: '/channels/teams', icon: Users, description: 'The same as Slack, inside Microsoft Teams chats and channels.', includes: ['The same as Slack, inside Microsoft Teams chats and channels'] },
];

export const kindInfo = (type: ChannelType) => KINDS.find((k) => k.type === type)!;

/** The fixed status words: never a bare count. */
export const HEALTH_WORD: Record<ChannelHealth, string> = { ok: 'Active', warn: 'Needs attention', error: 'Failing', idle: 'Not set up' };
export const HEALTH_DOT: Record<ChannelHealth, string> = { ok: 'bg-success-text', warn: 'bg-warning-text', error: 'bg-destructive', idle: 'bg-muted-foreground/40' };
