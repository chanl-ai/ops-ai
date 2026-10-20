import type { ChannelFilters, ChannelKindSummary, ChannelPatch, ChannelRow, LivePlaces, Mailbox, MailboxInput, MailboxPatch, MailboxTest } from '../types/channels';
import type { ListResult } from '../types/query';

/** Channels on agents-service: every channel as one record (c-242), and the mailboxes' own settings. */
export interface ChannelsApi {
  /** The team's channels, filtered and counted on the server; `kinds` is one summary per kind for the gallery and tabs. */
  list(params: { page: number; pageSize: number } & ChannelFilters): Promise<ListResult<ChannelRow> & { kinds: ChannelKindSummary[] }>;
  /**
   * Paused, or the version a chat embed serves (it keeps its agent; an email's comes from its workflow's trigger). The
   * row when applied, or `{ reviewId }` when the team's publish-review setting holds the change for a person.
   */
  change(id: string, patch: ChannelPatch): Promise<ChannelRow | { reviewId: string }>;
  /** Every place an agent or workflow answers, with the version live there. */
  live(kind: 'agent' | 'workflow', id: string): Promise<LivePlaces>;
  mailboxes(search?: string): Promise<Mailbox[]>;
  mailbox(id: string): Promise<Mailbox>;
  connectMailbox(input: MailboxInput): Promise<Mailbox>;
  editMailbox(id: string, patch: MailboxPatch): Promise<Mailbox>;
  /** An unsaved form (`input`) or a saved mailbox (`id`). */
  testMailbox(target: { input: MailboxInput } | { id: string }): Promise<MailboxTest>;
}
