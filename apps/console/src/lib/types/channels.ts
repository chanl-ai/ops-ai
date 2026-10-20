// Team mailboxes connected on Channels > Email (agents-service /v1/channels/mailboxes, c-199). A workflow's Email
// received trigger names a mailbox by address; a password is the name of a secret on the Secrets page, never its value.

/** gmail and imap are read over IMAP by tools-service; graph is not read yet. */
export type MailProvider = 'gmail' | 'imap' | 'graph';
/** How a mailbox's replies leave; none means send_reply naming it fails with that reason. */
export type ReplySender = 'none' | 'smtp' | 'resend' | 'graph';

export interface BoundWorkflow {
  id: string;
  name: string;
  version: number;
}

export interface Mailbox {
  id: string;
  teamId: string;
  name: string;
  address: string;
  provider: MailProvider;
  imapHost: string | null;
  imapPort: number | null;
  imapTls: boolean;
  username: string | null;
  /** The Secrets-page secret holding the password or app password; for Microsoft 365, the app's client secret. */
  passwordSecret: string | null;
  /** Microsoft 365: the app registration's Microsoft tenant and client id. */
  graphTenantId?: string | null;
  graphClientId?: string | null;
  folder: string;
  sender: ReplySender;
  fromAddress: string | null;
  smtpHost: string | null;
  smtpPort: number | null;
  smtpStarttls: boolean;
  /** The Secrets-page secret with the SMTP password or the Resend API key. */
  senderSecret: string | null;
  paused: boolean;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  /** The live workflows whose Email received trigger watches it. */
  workflows: BoundWorkflow[];
  /** When the listener last read it for those workflows; null before the first read. */
  lastReadAt: string | null;
}

export interface MailboxInput {
  name: string;
  address: string;
  provider: MailProvider;
  imapHost?: string | null;
  imapPort?: number | null;
  imapTls?: boolean;
  username?: string | null;
  passwordSecret?: string | null;
  graphTenantId?: string | null;
  graphClientId?: string | null;
  folder?: string;
  sender?: ReplySender;
  fromAddress?: string | null;
  smtpHost?: string | null;
  smtpPort?: number | null;
  smtpStarttls?: boolean;
  senderSecret?: string | null;
}

// Pausing is the channel's: ChannelPatch through PATCH /v1/channels/{id}.
export type MailboxPatch = Partial<Omit<MailboxInput, 'provider'>>;

export interface MailboxTestStep {
  title: string;
  state: 'done' | 'failed' | 'skipped';
}

/** Test connection: sign-in, then the folder's newest message read without marking it read, or why it failed. */
export interface MailboxTest {
  ok: boolean;
  steps: MailboxTestStep[];
  newest: { from: string; subject: string; date: string } | null;
  error: string | null;
}

/** The kinds a channel can be; MCP, Slack and Teams are listed as coming soon (built: false). */
export type ChannelType = 'email' | 'chat' | 'api' | 'mcp' | 'slack' | 'teams';
export type ChannelHealth = 'ok' | 'warn' | 'error' | 'idle';

/**
 * What a channel reaches: a workflow or an agent, at the latest published version or a pinned one. Null for an API key,
 * which may run anything its team may (c-246 binds a key to one target).
 */
export interface ChannelServes {
  kind: 'workflow' | 'agent';
  id: string;
  name: string;
  version: 'latest' | number;
  latestVersion: number;
  /** Versions published since the pinned one; 0 on Latest. */
  behind: number;
}

/** One row of GET /v1/channels (c-242): a mailbox, an embed or an API key as one channel record. */
export interface ChannelRow {
  /** The type's own record id, kept: mbx_ (mailbox), wd_ (embed), key_ (API key). */
  id: string;
  type: ChannelType;
  name: string;
  /** The address, the first allowed site, or the key's prefix. */
  detail: string;
  teamId: string;
  teamName: string;
  serves: ChannelServes | null;
  /** More than one workflow watches this mailbox; `serves` is the live one. */
  servesCount?: number;
  health: { state: ChannelHealth; reason?: string | null; checkedAt?: string | null };
  paused: boolean;
  /** Counted on the server; null where the channel leaves no mark to count (an API key today). */
  traffic24h: number | null;
  errors24h: number | null;
  activity7d: number | null;
  lastActivityAt: string | null;
  canEdit?: boolean;
}

/** One card of the gallery and one channel tab: a kind's health is the worst of its channels'. */
export interface ChannelKindSummary {
  type: ChannelType;
  built: boolean;
  health: ChannelHealth;
  active: number;
  attention: number;
  total: number;
}

export interface ChannelFilters {
  type?: string[];
  health?: string[];
  search?: string;
}

/** What a channel change sends: what it serves, or paused. */
export type ChannelPatch = { serves: { kind: 'workflow' | 'agent'; id: string; version: 'latest' | number } } | { paused: boolean };

/** GET /v1/agents/{id}/live (or a workflow's): every place it answers, with the version live there. */
export interface LivePlaces {
  latestVersion: number;
  versions: { version: number; places: number }[];
  rows: {
    /** A workflow step names the workflow it belongs to in `workflowId`. */
    where: { kind: 'channel' | 'workflow_step'; id: string; name: string; type?: ChannelType; workflowId?: string };
    version: number;
    pinned: boolean;
    behind: number;
    health: ChannelHealth;
    traffic24h: number | null;
    errors24h: number | null;
    lastActivityAt: string | null;
  }[];
}
