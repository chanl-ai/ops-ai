import type { AccountProfile, AccountSession, MfaDevice } from '@/lib/types/account';

import type { AccountApi } from '../../account-contract';
import { ApiError } from '../../contract';
import { auditSink } from '../governance';
import { id, list, notFound, respond } from '../runtime';

const MIN = 60_000;
const ago = (m: number) => new Date(Date.now() - m * MIN).toISOString();
const initialsOf = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('');
const codes = () => Array.from({ length: 10 }, () => `${Math.random().toString(36).slice(2, 6)}-${Math.random().toString(36).slice(2, 6)}`);

export interface AccountPerson {
  id: string;
  email: string;
  name: string;
  method: 'password' | 'sso' | 'google';
  mfaEnrolled: boolean;
}

interface Stored {
  name: string;
  devices: MfaDevice[];
  sessions: AccountSession[];
}

/**
 * The signed-in person's account. `person` reads who is signed in from the auth adapter; `setPassword` hands a
 * changed password back to it so the next sign-in accepts it. Sessions are per person and seeded on first read.
 */
export function createAccountMock(deps: { person: () => AccountPerson; setPassword?: (email: string, password: string) => void; mfaRequired: () => boolean; teamOf: (email: string) => { team: string; role: string } }) {
  const store = new Map<string, Stored>();
  const of = (p: AccountPerson): Stored => {
    const hit = store.get(p.id);
    if (hit) return hit;
    const s: Stored = {
      name: p.name,
      devices: p.mfaEnrolled
        ? [
            { id: id('mfa'), kind: 'totp', label: 'Authenticator app · iPhone', addedAt: ago(60 * 24 * 41), lastUsedAt: ago(35) },
            { id: id('mfa'), kind: 'recovery_codes', label: 'Recovery codes', addedAt: ago(60 * 24 * 41), remaining: 8 },
          ]
        : [],
      sessions: [
        { id: id('ses'), device: 'MacBook Pro', browser: 'Chrome 141', location: 'Toronto, ON', ip: '10.42.8.17', lastSeenAt: new Date().toISOString(), createdAt: ago(95), current: true },
        { id: id('ses'), device: 'Windows desktop · branch 014', browser: 'Edge 140', location: 'Mississauga, ON', ip: '10.61.2.44', lastSeenAt: ago(60 * 20), createdAt: ago(60 * 26), current: false },
        { id: id('ses'), device: 'iPhone 16', browser: 'Safari', location: 'Toronto, ON', ip: '172.20.1.9', lastSeenAt: ago(60 * 3), createdAt: ago(60 * 48), current: false },
        { id: id('ses'), device: 'Citrix workspace', browser: 'Chrome 139', location: 'Montréal, QC', ip: '10.12.0.201', lastSeenAt: ago(60 * 24 * 4), createdAt: ago(60 * 24 * 5), current: false },
      ],
    };
    store.set(p.id, s);
    return s;
  };
  const me = () => {
    const p = deps.person();
    return { p, s: of(p) };
  };
  const profileOf = (): AccountProfile => {
    const { p, s } = me();
    const t = deps.teamOf(p.email);
    return { id: p.id, name: s.name, email: p.email, initials: initialsOf(s.name), team: t.team, role: t.role, authMethod: p.method === 'password' ? 'password' : 'sso', ssoProvider: p.method === 'password' ? undefined : p.method === 'google' ? 'Google' : 'Microsoft Entra ID' };
  };
  const log = (p: AccountPerson, summary: string) => auditSink.log({ action: 'edited', target: { type: 'session', name: p.email, href: '/settings/account/security' }, summary });

  const api: AccountApi = {
    profile: () => respond(() => profileOf()),
    updateProfile: (input) =>
      respond(() => {
        const { p, s } = me();
        const name = input.name.trim();
        if (name.length < 2 || name.length > 80) throw new ApiError('Enter your name in 2 to 80 characters.', 400);
        const before = s.name;
        s.name = name;
        auditSink.log({ action: 'edited', target: { type: 'member', name: p.email, href: '/settings/account' }, summary: 'Changed their display name', diff: [{ field: 'Name', before, after: name }] });
        return profileOf();
      }),
    changePassword: (input) =>
      respond(() => {
        const { p } = me();
        if (p.method !== 'password') throw new ApiError('Your account signs in with SSO; its password is managed by your identity provider.', 403);
        if (input.password.length < 12) throw new ApiError('Use at least 12 characters.', 400);
        deps.setPassword?.(p.email, input.password);
        log(p, 'Changed their password; other sessions stay signed in');
      }),
    mfa: {
      list: () => respond((m) => (m === 'empty' ? [] : me().s.devices)),
      regenerateCodes: () =>
        respond(() => {
          const { p, s } = me();
          const fresh = codes();
          const existing = s.devices.find((d) => d.kind === 'recovery_codes');
          if (existing) Object.assign(existing, { remaining: fresh.length, addedAt: new Date().toISOString() });
          else s.devices.push({ id: id('mfa'), kind: 'recovery_codes', label: 'Recovery codes', addedAt: new Date().toISOString(), remaining: fresh.length });
          log(p, 'Regenerated their recovery codes; the old ones stop working');
          return { codes: fresh, devices: s.devices };
        }),
      remove: (did) =>
        respond(() => {
          const { p, s } = me();
          const d = s.devices.find((x) => x.id === did) ?? notFound('Device');
          if (d.kind === 'totp' && deps.mfaRequired() && s.devices.filter((x) => x.kind === 'totp').length === 1) throw new ApiError('Your workspace requires two-step verification. Add another authenticator before removing this one.', 409);
          s.devices = s.devices.filter((x) => x !== d);
          log(p, `Removed ${d.label}`);
          return s.devices;
        }),
    },
    sessions: {
      list: (params) => respond((m) => list([...me().s.sessions].sort((a, b) => Number(b.current) - Number(a.current) || b.lastSeenAt.localeCompare(a.lastSeenAt)), params, { text: (x) => `${x.device} ${x.browser} ${x.location} ${x.ip}`, value: (x, k) => (k === 'current' ? String(x.current) : String((x as unknown as Record<string, unknown>)[k])), facetKeys: [] }, m)),
      revoke: (sid) =>
        respond(() => {
          const { p, s } = me();
          const x = s.sessions.find((y) => y.id === sid) ?? notFound('Session');
          if (x.current) throw new ApiError('That is this session. Sign out instead.', 400);
          s.sessions = s.sessions.filter((y) => y !== x);
          log(p, `Signed out ${x.device} (${x.location})`);
        }),
      revokeOthers: () =>
        respond(() => {
          const { p, s } = me();
          const n = s.sessions.filter((x) => !x.current).length;
          s.sessions = s.sessions.filter((x) => x.current);
          log(p, `Signed out everywhere else (${n} sessions)`);
          return { revoked: n };
        }),
    },
  };
  return { api };
}
