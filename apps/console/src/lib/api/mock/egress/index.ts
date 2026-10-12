import type { EgressApi } from '../../egress-contract';
import { ApiError } from '../../contract';
import { respond } from '../runtime';
import type { ListedHost, ListedRange } from '@/lib/types/egress';

const HOST = /^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
const CIDR = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/;

/** The service's rules for what may be listed: a DNS name, never an address; private ranges only, never loopback, link-local or metadata. */
function checked(kind: 'host' | 'range', raw: string): string {
  const value = raw.trim().toLowerCase();
  if (kind === 'host') {
    if (!HOST.test(value)) throw new ApiError(`${raw} is not a host name. List a DNS name such as api.bank.example; addresses go in private ranges.`, 400);
    return value;
  }
  const m = CIDR.exec(value);
  if (!m || m.slice(1, 5).some((o) => Number(o) > 255) || Number(m[5]) > 32) throw new ApiError(`${raw} is not an IPv4 range such as 10.20.0.0/16.`, 400);
  const [a, b] = [Number(m[1]), Number(m[2])];
  if (a === 127) throw new ApiError(`${value} is loopback, which tool calls may never reach.`, 400);
  if (a === 169 && b === 254) throw new ApiError(`${value} is link-local, which holds cloud metadata; tool calls may never reach it.`, 400);
  const isPrivate = a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
  if (!isPrivate) throw new ApiError(`${value} is not a private range. Public addresses need no listing; only the host does.`, 400);
  return value;
}

/** The allow-list in memory, seeded with the hosts the seeded modules call. `inUse` maps a host to its modules' names. */
export function createEgressMock(deps: { me: string; inUse: () => Record<string, string[]> }): EgressApi {
  const at = new Date(Date.now() - 86_400_000 * 12).toISOString();
  const hosts: Omit<ListedHost, 'modules'>[] = Object.keys(deps.inUse()).map((host) => ({ host, note: 'Seeded with its tool module', addedBy: 'Platform team', addedAt: at }));
  const ranges: ListedRange[] = [{ cidr: '10.20.0.0/16', note: 'Core banking network', addedBy: 'Platform team', addedAt: at }];
  return {
    list: () => respond(() => ({ hosts: hosts.map((h) => ({ ...h, modules: deps.inUse()[h.host] ?? [] })), ranges })),
    add: (kind, raw, note) =>
      respond(() => {
        const value = checked(kind, raw);
        const rows: { value: string }[] = kind === 'host' ? hosts.map((h) => ({ value: h.host })) : ranges.map((r) => ({ value: r.cidr }));
        if (rows.some((r) => r.value === value)) return { kind, value, changed: false };
        const row = { note: note.trim(), addedBy: deps.me, addedAt: new Date().toISOString() };
        if (kind === 'host') hosts.push({ host: value, ...row });
        else ranges.push({ cidr: value, ...row });
        return { kind, value, changed: true };
      }),
    remove: (kind, raw) =>
      respond(() => {
        const value = checked(kind, raw);
        const users = kind === 'host' ? (deps.inUse()[value] ?? []) : [];
        if (users.length) throw new ApiError(`${value} is called by ${users.join(', ')}. Change those modules first.`, 409);
        const list: { host?: string; cidr?: string }[] = kind === 'host' ? hosts : ranges;
        const i = list.findIndex((r) => (r.host ?? r.cidr) === value);
        if (i < 0) throw new ApiError(`${value} on the egress allow-list not found`, 404);
        list.splice(i, 1);
        return { kind, value, changed: true };
      }),
  };
}
