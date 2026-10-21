import { ApiError } from '../contract';
import type { ChannelsApi } from '../channels-contract';
import type { ChannelKindSummary, ChannelRow, Mailbox } from '../../types/channels';

/** One sample mailbox so Channels > Email renders on the mock; connecting and testing work in memory. */
export function createChannelsMock(): ChannelsApi {
  const now = new Date().toISOString();
  const rows: Mailbox[] = [
    {
      id: 'mbx_sample_levies',
      teamId: 'team_ops',
      name: 'Levy notices',
      address: 'levies@harborpine.example',
      provider: 'imap',
      imapHost: 'mail.harborpine.example',
      imapPort: 993,
      imapTls: true,
      username: null,
      passwordSecret: 'LEVY_MAILBOX_PASSWORD',
      folder: 'inbox',
      sender: 'smtp',
      fromAddress: 'levies@harborpine.example',
      smtpHost: 'smtp.harborpine.example',
      smtpPort: 587,
      smtpStarttls: true,
      senderSecret: 'LEVY_MAILBOX_PASSWORD',
      paused: false,
      createdBy: 'j.richardson@harborpine.example',
      createdAt: now,
      updatedAt: now,
      workflows: [],
      lastReadAt: null,
    },
  ];
  const find = (id: string) => {
    const m = rows.find((r) => r.id === id);
    if (!m) throw new ApiError(`Mailbox ${id} not found`, 404);
    return m;
  };
  // The mock's channels are its mailboxes; embeds and keys need the agents service.
  const asChannel = (m: Mailbox): ChannelRow => ({ id: m.id, type: 'email', name: m.name, detail: m.address, teamId: m.teamId, teamName: 'Operations', serves: null, health: { state: m.paused ? 'idle' : 'ok' }, paused: !!m.paused, traffic24h: 0, errors24h: 0, activity7d: 0, lastActivityAt: null, canEdit: true });
  const kinds = (): ChannelKindSummary[] =>
    (['email', 'chat', 'api', 'mcp', 'slack', 'teams'] as const).map((type) => {
      const mine = type === 'email' ? rows : [];
      return { type, built: ['email', 'chat', 'api'].includes(type), health: mine.some((m) => !m.paused) ? 'ok' : 'idle', active: mine.filter((m) => !m.paused).length, attention: 0, total: mine.length };
    });
  return {
    list: async ({ page, pageSize, type }) => {
      const data = rows.map(asChannel).filter((c) => !type?.length || type.includes(c.type));
      return { data: data.slice((page - 1) * pageSize, page * pageSize), pagination: { page, pageSize, total: data.length, totalPages: Math.max(1, Math.ceil(data.length / pageSize)), hasNext: page * pageSize < data.length, hasPrev: page > 1 }, facets: {}, kinds: kinds() };
    },
    change: async (id, patch) => {
      const m = rows.find((r) => r.id === id);
      if (!m) throw new ApiError(`Channel ${id} was not found.`, 404);
      if ('paused' in patch) m.paused = patch.paused;
      return asChannel(m);
    },
    live: async () => ({ latestVersion: 1, versions: [], rows: [] }),
    mailboxes: async (search) => rows.filter((r) => !search || `${r.name} ${r.address}`.toLowerCase().includes(search.toLowerCase())),
    mailbox: async (id) => find(id),
    connectMailbox: async (input) => {
      if (rows.some((r) => r.address.toLowerCase() === input.address.toLowerCase())) throw new ApiError(`${input.address} is connected already in this workspace.`, 409);
      const at = new Date().toISOString();
      const m: Mailbox = { id: `mbx_${Math.random().toString(36).slice(2, 10)}`, teamId: 'team_ops', imapHost: null, imapPort: null, imapTls: true, username: null, passwordSecret: null, folder: 'inbox', sender: 'none', fromAddress: null, smtpHost: null, smtpPort: null, smtpStarttls: true, senderSecret: null, ...input, paused: false, createdBy: 'you', createdAt: at, updatedAt: at, workflows: [], lastReadAt: null } as Mailbox;
      rows.push(m);
      return m;
    },
    editMailbox: async (id, patch) => Object.assign(find(id), patch, { updatedAt: new Date().toISOString() }),
    testMailbox: async () => ({ ok: true, steps: [{ title: 'Sign in', state: 'done' }], newest: null, error: null }),
  };
}
