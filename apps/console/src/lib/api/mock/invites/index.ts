import type { InviteAcceptResult, InvitePreview } from '@/lib/types/invites';

import { ApiError } from '../../contract';
import type { InvitesApi } from '../../invites-contract';
import { auditSink } from '../governance';
import { notFound, respond } from '../runtime';

const DAY = 86_400_000;
/** Links last a week, as in the bank's joiner process. */
const VALID_MS = 7 * DAY;

interface StoredInvite {
  token: string;
  email: string;
  team: string;
  teamId: string;
  role: string;
  invitedBy: string;
  invitedAt: string;
  acceptedAt?: string;
  acceptedName?: string;
}

// The registry is module-level so the settings mock can register the invites Members creates and read back who
// accepted, without the two slices importing each other.
const invites = new Map<string, StoredInvite>();
const tokenFor = (email: string, teamId: string) => `inv_${[...`${email}:${teamId}`].reduce((h, c) => (h * 33 + c.charCodeAt(0)) >>> 0, 5381).toString(36)}`;

/** Called by Settings → Members for every invite it sends (and for seeded invited members). Returns the link token. */
export function registerInvite(i: Omit<StoredInvite, 'token' | 'acceptedAt' | 'acceptedName'>): string {
  const token = tokenFor(i.email, i.teamId);
  if (!invites.has(token)) invites.set(token, { ...i, token });
  return token;
}

/** The name an invitee gave when accepting, or undefined while the invite is open. */
export const acceptedName = (email: string, teamId: string) => invites.get(tokenFor(email, teamId))?.acceptedName;

// Fixed demo links: an open password invite, an open SSO invite, an expired one and a used one.
const seed = (token: string, i: Omit<StoredInvite, 'token'>) => invites.set(token, { ...i, token });
seed('demo-invite', { email: 'sam.ortiz@harborpine.example', team: 'Lending Ops', teamId: 'team_lending', role: 'Reviewer', invitedBy: 'James Richardson', invitedAt: new Date(Date.now() - 2 * 3_600_000).toISOString() });
seed('demo-invite-sso', { email: 'li.chen@harborpine.ca', team: 'Card Services', teamId: 'team_cards', role: 'Builder', invitedBy: 'Maya Okafor', invitedAt: new Date(Date.now() - 26 * 3_600_000).toISOString() });
seed('demo-invite-expired', { email: 'r.patel@harborpine.example', team: 'Fraud Strategy', teamId: 'team_fraud', role: 'Viewer', invitedBy: 'Daniel Brooks', invitedAt: new Date(Date.now() - 9 * DAY).toISOString() });
seed('demo-invite-used', { email: 'grace.kim@harborpine.example', team: 'Retail Banking', teamId: 'team_retail', role: 'Builder', invitedBy: 'Anika Singh', invitedAt: new Date(Date.now() - 3 * DAY).toISOString(), acceptedAt: new Date(Date.now() - 2 * DAY).toISOString(), acceptedName: 'Grace Kim' });

const PASSWORD_MIN = 12;

/**
 * Invite links over the registry. `isSsoEmail` and `mfaRequired` come from the sign-in policy; `onAccepted` hands the
 * new account to the auth adapter so it can sign in.
 */
export function createInvitesMock(deps: {
  isSsoEmail: (email: string) => boolean;
  ssoProviderLabel: () => string;
  mfaRequired: () => boolean;
  onAccepted?: (a: { email: string; name: string; teamId: string; role: string; method: 'password' | 'sso'; password: string | null }) => void;
}) {
  const stateOf = (i: StoredInvite): InvitePreview['state'] => (i.acceptedAt ? 'accepted' : Date.now() - new Date(i.invitedAt).getTime() > VALID_MS ? 'expired' : 'pending');
  const preview = (i: StoredInvite): InvitePreview => {
    const sso = deps.isSsoEmail(i.email);
    return {
      token: i.token,
      email: i.email,
      team: i.team,
      role: i.role,
      invitedBy: i.invitedBy,
      invitedAt: i.invitedAt,
      expiresAt: new Date(new Date(i.invitedAt).getTime() + VALID_MS).toISOString(),
      state: stateOf(i),
      sso,
      ssoProviderLabel: sso ? deps.ssoProviderLabel() : undefined,
      mfaRequired: deps.mfaRequired(),
    };
  };
  const find = (token: string) => invites.get(token) ?? notFound('Invitation');

  const api: InvitesApi = {
    get: (token) => respond((m) => (m === 'empty' ? notFound('Invitation') : preview(find(token)))),
    accept: (token, input) =>
      respond((): InviteAcceptResult => {
        const i = find(token);
        const state = stateOf(i);
        if (state === 'expired') throw new ApiError(`This invitation expired. Ask ${i.invitedBy} to send a new one.`, 410);
        if (state === 'accepted') throw new ApiError('This invitation was already used. Sign in instead.', 409);
        const name = input.name.trim();
        if (name.length < 2) throw new ApiError('Enter your name.', 400);
        const sso = deps.isSsoEmail(i.email);
        if (!sso) {
          const pw = input.password ?? '';
          if (pw.length < PASSWORD_MIN) throw new ApiError(`Use at least ${PASSWORD_MIN} characters.`, 400);
          if (pw.toLowerCase().includes(i.email.split('@')[0].toLowerCase())) throw new ApiError('Do not use your name or email in the password.', 400);
        }
        Object.assign(i, { acceptedAt: new Date().toISOString(), acceptedName: name });
        deps.onAccepted?.({ email: i.email, name, teamId: i.teamId, role: i.role, method: sso ? 'sso' : 'password', password: sso ? null : (input.password ?? null) });
        auditSink.log({ action: 'edited', target: { type: 'member', name: i.email, href: '/settings/members' }, summary: `${name} accepted the invitation to ${i.team}${sso ? ' and signs in with SSO' : ''}`, diff: [{ field: 'Status', before: 'Invited', after: 'Active' }] });
        return { email: i.email, name, team: i.team, authMethod: sso ? 'sso' : 'password', next: deps.mfaRequired() ? '/mfa/setup' : '/' };
      }),
  };
  return { api };
}
