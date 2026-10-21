/**
 * Sample rows for the channels mock (/preview/channels). Nothing here is read from or written to a service; the shapes
 * follow ops_email (a mailbox source chosen by provider, a sender chosen by settings) and the c-187 trigger binding.
 */
const ago = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

export const ROOT = '/preview/channels';

export type ChannelType = 'email' | 'chat' | 'api' | 'mcp' | 'slack' | 'teams';
export type ConnectionStatus = 'connected' | 'attention' | 'paused';

export interface ChannelTypeInfo {
  type: ChannelType;
  title: string;
  description: string;
  href: string;
  built: boolean;
  /** What a connection of this kind gives a team, for its landing page. */
  includes: string[];
}

/** One card per kind of channel. `built` is false for the ones no service serves yet. */
export const CHANNEL_TYPES: ChannelTypeInfo[] = [
  { type: 'email', title: 'Email mailbox', description: 'A new email in a watched folder starts a workflow; replies go out through a sender you choose.', href: `${ROOT}/email`, built: true, includes: ['Each new email in a watched folder starts the workflow it serves', 'Attachments land in Files, linked from the run', 'Replies go out through the sender the mailbox names', 'Sign-in secrets come from the Secrets list, never typed here'] },
  { type: 'chat', title: 'Chat embed', description: 'An agent’s chat on one of the bank’s own pages, pinned to a published version.', href: `${ROOT}/chat`, built: true, includes: ['An agent’s chat on the bank’s own pages, signed in with the person’s SSO', 'Pinned to a published version, or following the latest', 'Sites allowed, mint keys and 7-day usage per embed', 'Pause or retire an embed without touching the agent'] },
  { type: 'api', title: 'API', description: 'The bank’s systems start runs with an API key and read what happened.', href: `${ROOT}/api`, built: true, includes: ['The bank’s systems start runs with an API key', 'Each key names the workflows it may start', 'Calls and their outcomes, per key', 'Revoke a key at once'] },
  { type: 'mcp', title: 'MCP', description: 'Offer a published workflow as a tool to assistants that speak MCP.', href: `${ROOT}/mcp`, built: false, includes: ['Offer a published workflow as a tool to assistants', 'Each person signs in with their own account', 'Calls held for approval wait in Human Tasks'] },
  { type: 'slack', title: 'Slack', description: 'People ask an agent in a channel or a direct message and get the answer in the thread.', href: `${ROOT}/slack`, built: false, includes: ['Ask an agent in a channel or a direct message', 'The answer comes back in the thread'] },
  { type: 'teams', title: 'Teams', description: 'The same as Slack, inside Microsoft Teams chats and channels.', href: `${ROOT}/teams`, built: false, includes: ['The same as Slack, inside Microsoft Teams chats and channels'] },
];

export type MailProvider = 'gmail' | 'graph' | 'imap';
export type SenderKind = 'smtp' | 'resend' | 'graph';

export const PROVIDERS: { value: MailProvider; title: string; description: string }[] = [
  { value: 'gmail', title: 'Gmail', description: 'IMAP with an app password. Turn on two-step verification in the Google account first.' },
  { value: 'graph', title: 'Microsoft 365', description: 'Reads through Microsoft Graph with an app registration the bank’s admin grants.' },
  { value: 'imap', title: 'Other IMAP', description: 'Any server that speaks IMAP over TLS, with a user name and password.' },
];
export const PROVIDER_LABEL: Record<MailProvider, string> = { gmail: 'Gmail', graph: 'Microsoft 365', imap: 'IMAP' };

export const SENDERS: { value: SenderKind; title: string; description: string }[] = [
  { value: 'smtp', title: 'SMTP', description: 'The bank’s own mail server, or Gmail’s with the same app password.' },
  { value: 'resend', title: 'Resend', description: 'A sending service, with an API key kept in Secrets.' },
  { value: 'graph', title: 'Microsoft 365', description: 'Sends as the mailbox through the same app registration.' },
];
export const SENDER_LABEL: Record<SenderKind, string> = { smtp: 'SMTP', resend: 'Resend', graph: 'Microsoft 365' };

/** What a test connection lists as the mailbox's folders. */
export const FOLDERS = ['Inbox', 'Levies', 'Disputes', 'Hardship', 'Archive'];

export interface MailboxSettings {
  provider: MailProvider;
  address: string;
  /** IMAP host and port; Gmail's are fixed. */
  host: string;
  port: string;
  username: string;
  /** Microsoft 365 app registration. */
  tenantId: string;
  clientId: string;
  /** The name of a secret on the Secrets page: the IMAP password, or the app registration's client secret. */
  secret: string | null;
  folder: string;
  sender: SenderKind;
  fromAddress: string;
  /** SMTP server as host:port. */
  smtpHost: string;
  /** SMTP password or Resend API key, by name. Microsoft 365 sends with the reading credentials. */
  senderSecret: string | null;
}

export interface BoundWorkflow {
  id: string;
  name: string;
  status: 'live' | 'draft';
}

/** A published workflow or agent a connection can serve, with its versions newest first. */
export interface ServeOption {
  kind: 'workflow' | 'agent';
  id: string;
  name: string;
  versions: number[];
}

export const SERVE_OPTIONS: ServeOption[] = [
  { kind: 'workflow', id: 'wf_levy_intake', name: 'Levy intake', versions: [3, 2, 1] },
  { kind: 'workflow', id: 'wf_card_inbox', name: 'Card services inbox', versions: [6, 5] },
  { kind: 'workflow', id: 'wf_lending_inbox', name: 'Lending servicing inbox', versions: [3, 2] },
  { kind: 'workflow', id: 'wf_dispute', name: 'Card dispute resolution', versions: [3, 2] },
  { kind: 'workflow', id: 'wf_kyb', name: 'Business account onboarding', versions: [2, 1] },
  { kind: 'workflow', id: 'wf_wire', name: 'Outbound wire review', versions: [7, 6] },
  { kind: 'agent', id: 'ag_advisor', name: 'Advisor’s Helper', versions: [5, 4, 3] },
  { kind: 'agent', id: 'ag_branch', name: 'Branch Concierge', versions: [3, 2] },
  { kind: 'agent', id: 'ag_fraud', name: 'Wire Fraud Sentinel', versions: [8, 7] },
];

/** What a connection reaches: a workflow or an agent, at its latest published version or pinned to one. */
export interface Serves {
  kind: 'workflow' | 'agent';
  id: string;
  version: 'latest' | number;
}

export const serveOption = (s: Serves) => SERVE_OPTIONS.find((o) => o.kind === s.kind && o.id === s.id);

/** "Levy intake workflow · latest published (v3)" or "Advisor’s Helper · v4 pinned, 1 behind". */
export function servesLabel(s: Serves): string {
  const o = serveOption(s);
  if (!o) return 'Nothing yet';
  const name = o.kind === 'workflow' ? `${o.name} workflow` : o.name;
  if (s.version === 'latest') return `${name} · latest published (v${o.versions[0]})`;
  const behind = o.versions.indexOf(s.version);
  return `${name} · v${s.version} pinned${behind > 0 ? `, ${behind} behind` : ''}`;
}

export interface Connection {
  id: string;
  type: ChannelType;
  name: string;
  serves: Serves;
  /** Conversations, emails or calls in the last 24 hours, and how many of them failed. */
  traffic24h: number;
  errors24h: number;
  /** Rows the Activity page lists for this connection over the last 7 days. */
  activity7d: number;
  /** The address, page or key the connection is known by. */
  detail: string;
  status: ConnectionStatus;
  /** Why it needs attention, in a sentence. */
  problem?: string;
  lastActivityAt?: string;
  team: string;
  workflows: BoundWorkflow[];
  mailbox?: MailboxSettings;
  lastMessage?: { from: string; subject: string; at: string };
}

export const blankMailbox = (provider: MailProvider): MailboxSettings => ({
  provider,
  address: '',
  host: provider === 'gmail' ? 'imap.gmail.com' : '',
  port: '993',
  username: '',
  tenantId: '',
  clientId: '',
  secret: null,
  folder: 'Inbox',
  sender: provider === 'graph' ? 'graph' : 'smtp',
  fromAddress: '',
  smtpHost: provider === 'gmail' ? 'smtp.gmail.com:587' : '',
  senderSecret: null,
});

/** The secret whose app password Google revoked, so the mock can show a failing test. */
export const REVOKED_SECRET = 'DISPUTES_APP_PASSWORD';

export const CONNECTIONS: Connection[] = [
  {
    id: 'mbx_7f3a91c2',
    type: 'email',
    name: 'Card services', serves: { kind: 'workflow', id: 'wf_card_inbox', version: 'latest' }, traffic24h: 236, errors24h: 0, activity7d: 1412,
    detail: 'cardservices@harborpine.example',
    status: 'connected',
    lastActivityAt: ago(12),
    team: 'Operations',
    workflows: [{ id: 'wf_card_inbox', name: 'Card services inbox', status: 'live' }],
    lastMessage: { from: 'm.chen@mail.example', subject: 'Charge I don’t recognise on my Visa', at: ago(12) },
    mailbox: { ...blankMailbox('graph'), address: 'cardservices@harborpine.example', tenantId: '3f1c7a90-2b8e-4d5f-9a61-7e0c4b2d8f13', clientId: 'a7d2e4b1-6c39-4f80-b5a2-19e8c3d7f064', secret: 'GRAPH_CLIENT_SECRET', fromAddress: 'cardservices@harborpine.example' },
  },
  {
    id: 'mbx_c41e8b07',
    type: 'email',
    name: 'Lending servicing', serves: { kind: 'workflow', id: 'wf_lending_inbox', version: 'latest' }, traffic24h: 118, errors24h: 2, activity7d: 690,
    detail: 'lendingservicing@harborpine.example',
    status: 'connected',
    lastActivityAt: ago(47),
    team: 'Lending',
    workflows: [{ id: 'wf_lending_inbox', name: 'Lending servicing inbox', status: 'live' }],
    lastMessage: { from: 'a.romero@mail.example', subject: 'Payoff statement for loan ending 4471', at: ago(47) },
    mailbox: { ...blankMailbox('graph'), address: 'lendingservicing@harborpine.example', tenantId: '3f1c7a90-2b8e-4d5f-9a61-7e0c4b2d8f13', clientId: 'a7d2e4b1-6c39-4f80-b5a2-19e8c3d7f064', secret: 'GRAPH_CLIENT_SECRET', fromAddress: 'lendingservicing@harborpine.example' },
  },
  {
    id: 'mbx_5d92a6f3',
    type: 'email',
    name: 'Disputes test inbox', serves: { kind: 'workflow', id: 'wf_dispute', version: 2 }, traffic24h: 0, errors24h: 0, activity7d: 31,
    detail: 'northfield.disputes.test@gmail.com',
    status: 'attention',
    problem: 'Sign-in was refused 2 hours ago: the app password no longer works.',
    lastActivityAt: ago(60 * 26),
    team: 'Operations',
    workflows: [{ id: 'wf_dispute', name: 'Card dispute resolution', status: 'draft' }],
    lastMessage: { from: 'qa@harborpine.example', subject: 'Test dispute 31', at: ago(60 * 26) },
    mailbox: { ...blankMailbox('gmail'), address: 'northfield.disputes.test@gmail.com', username: 'northfield.disputes.test@gmail.com', secret: REVOKED_SECRET, folder: 'Disputes', fromAddress: 'northfield.disputes.test@gmail.com', smtpHost: 'smtp.gmail.com:587', senderSecret: REVOKED_SECRET },
  },
  {
    id: 'mbx_e08b3c5a',
    type: 'email',
    name: 'Business documents', serves: { kind: 'workflow', id: 'wf_kyb', version: 'latest' }, traffic24h: 0, errors24h: 0, activity7d: 12,
    detail: 'kyb-docs@harborpine.example',
    status: 'paused',
    lastActivityAt: ago(60 * 24 * 6),
    team: 'Operations',
    workflows: [{ id: 'wf_kyb', name: 'Business account onboarding', status: 'live' }],
    lastMessage: { from: 'filings@registry.example', subject: 'Certificate of status, 2291044 Ontario Inc.', at: ago(60 * 24 * 6) },
    mailbox: { ...blankMailbox('imap'), address: 'kyb-docs@harborpine.example', host: 'mail.harborpine.example', username: 'kyb-docs', secret: 'KYB_MAILBOX_PASSWORD', sender: 'resend', fromAddress: 'onboarding@harborpine.example', senderSecret: 'RESEND_API_KEY' },
  },
  { id: 'emb_2a7c9f14', type: 'chat', name: 'Branch site chat', serves: { kind: 'agent', id: 'ag_branch', version: 2 }, traffic24h: 583, errors24h: 2, activity7d: 3904, detail: 'www.harborpine.example/branches', status: 'connected', lastActivityAt: ago(3), team: 'Operations', workflows: [{ id: 'wf_branch_chat', name: 'Branch chat', status: 'live' }] },
  {
    id: 'mbx_levy01c4',
    type: 'email',
    name: 'Court levies',
    serves: { kind: 'workflow', id: 'wf_levy_intake', version: 'latest' },
    traffic24h: 14,
    errors24h: 0,
    activity7d: 88,
    detail: 'levies@harborpine.example',
    status: 'connected',
    lastActivityAt: ago(9),
    team: 'Operations',
    workflows: [{ id: 'wf_levy_intake', name: 'Levy intake', status: 'live' }],
    lastMessage: { from: 'registry@courts.example', subject: 'Notice of garnishment NS-2026-GN-01187', at: ago(9) },
    mailbox: { ...blankMailbox('graph'), address: 'levies@harborpine.example', tenantId: '3f1c7a90-2b8e-4d5f-9a61-7e0c4b2d8f13', clientId: 'a7d2e4b1-6c39-4f80-b5a2-19e8c3d7f064', secret: 'GRAPH_CLIENT_SECRET', folder: 'Levies', fromAddress: 'levies@harborpine.example' },
  },
  { id: 'emb_9c41ad70', type: 'chat', name: 'Advisor intranet', serves: { kind: 'agent', id: 'ag_advisor', version: 'latest' }, traffic24h: 212, errors24h: 0, activity7d: 1340, detail: 'intranet.harborpine.example/advice', status: 'connected', lastActivityAt: ago(6), team: 'Operations', workflows: [] },
  { id: 'emb_4f0e2b9d', type: 'chat', name: 'Wealth portal', serves: { kind: 'agent', id: 'ag_advisor', version: 4 }, traffic24h: 41, errors24h: 0, activity7d: 260, detail: 'wealth.harborpine.example', status: 'connected', lastActivityAt: ago(31), team: 'Wealth', workflows: [] },
  { id: 'key_6b2e9d03', type: 'api', name: 'Core banking runs', serves: { kind: 'workflow', id: 'wf_wire', version: 'latest' }, traffic24h: 1204, errors24h: 3, activity7d: 8120, detail: 'opk_live_8f3a…', status: 'connected', lastActivityAt: ago(4), team: 'Operations', workflows: [{ id: 'wf_wire', name: 'Outbound wire review', status: 'live' }] },
];

/** Secrets the mock's mailboxes name, added beside the settings mock's own so the pickers find them. */
export const MAIL_SECRETS = ['GRAPH_CLIENT_SECRET', REVOKED_SECRET, 'KYB_MAILBOX_PASSWORD', 'RESEND_API_KEY'];

/** The workflow drawn on /preview/channels/trigger. Saving its trigger binds it to the mailbox picked. */
export const TRIGGER_WORKFLOW: BoundWorkflow = { id: 'wf_levy_intake', name: 'Levy notice intake', status: 'draft' };

/** The agent whose Channels tab (c-130) lists the workflows that call it; the email workflows above call it. */
export const AGENT_CHANNELS_HREF = '/agents/ag_kyb?tab=channels';
