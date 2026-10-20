import type { ChannelsApi } from './channels-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** `get` and `send` come from a client whose base URL ends in /v1 on agents-service. */
export function createChannelsHttp(get: Get, send: Send): ChannelsApi {
  const base = '/channels/mailboxes';
  return {
    list: ({ page, pageSize, type, health, search }) => {
      const q = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      for (const t of type ?? []) q.append('type', t);
      for (const h of health ?? []) q.append('health', h);
      if (search) q.set('search', search);
      return get(`/channels?${q}`);
    },
    change: (id, patch) => send('PATCH', `/channels/${encodeURIComponent(id)}`, patch),
    live: (kind, id) => get(`/${kind === 'agent' ? 'agents' : 'workflows'}/${encodeURIComponent(id)}/live`),
    mailboxes: (search) => get(`${base}${search ? `?${new URLSearchParams({ search })}` : ''}`),
    mailbox: (id) => get(`${base}/${encodeURIComponent(id)}`),
    connectMailbox: (input) => send('POST', base, input),
    editMailbox: (id, patch) => send('PATCH', `${base}/${encodeURIComponent(id)}`, patch),
    testMailbox: (target) => ('id' in target ? send('POST', `${base}/${encodeURIComponent(target.id)}/test`) : send('POST', `${base}/test`, target.input)),
  };
}
