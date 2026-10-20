import type { AuditEntry, AuditFilters, AuditTargetType, AuditView, AuditViewCounts } from '@/lib/types/governance';
import type { InvitePreview } from '@/lib/types/invites';
import type { ListParams, ListResult } from '@/lib/types/query';
import type { SignInOptions } from '@/lib/types/sign-in';

import type { OpsApi } from './contract';
import { createTransport } from './http';
import { optionsQs } from './options';

/** One audit row as platform-service returns it (GET /v1/audit): names, summary and action word joined by the service. */
interface PlatformAuditRow {
  id: string;
  at: string;
  teamId: string | null;
  team: string | null;
  actor: string;
  actorName: string | null;
  actorEmail: string | null;
  kind: AuditEntry['action'];
  summary: string;
  targetKind: string;
  targetId: string;
  targetName: string | null;
  requestId: string;
}

type PlatformInvite = Omit<InvitePreview, 'invitedBy' | 'sso' | 'mfaRequired' | 'passwordless'> & { invitedBy: string | null };

// People read reviewer for the stored approver (roles-and-permissions, open question 1). `chat_user` is the membership a
// first SSO sign-in gives a person new to the workspace (c-188).
const ROLE_LABEL: Record<string, string> = { admin: 'Admin', builder: 'Builder', approver: 'Reviewer', viewer: 'Viewer', chat_user: 'Chat user' };
const TARGETS = new Set<string>(['member', 'api_key', 'session', 'team']);

const entry = (r: PlatformAuditRow): AuditEntry => ({
  id: r.id,
  at: r.at,
  actor: { kind: 'person', name: r.actorName ?? r.actor, detail: r.actorEmail ?? '' },
  action: r.kind,
  target: { type: (TARGETS.has(r.targetKind) ? r.targetKind : 'member') as AuditTargetType, name: r.targetName ?? r.targetId },
  teamId: r.teamId ?? '',
  team: r.team ?? '',
  summary: r.summary,
  diff: [],
  requestId: r.requestId,
});

/**
 * Members, invitations and the audit log on platform-service, for a console signed in through it. Shapes are the
 * service's; this only renames fields. Accepting an invitation goes through the sign-in adapter, which keeps the
 * session platform-service answers it with.
 */
export function createPlatformAccessHttp(
  baseUrl: string,
  acceptInvite: (token: string, name: string, password?: string) => Promise<{ user: { email: string; name: string } }>,
  signInOptions: (email: string) => Promise<SignInOptions>,
): { members: OpsApi['settings']['members']; invites: OpsApi['invites']; audit: OpsApi['governance']['audit'] } {
  const { get, send, qs } = createTransport(`${baseUrl}/v1`);
  return {
    members: {
      list: (p) => get(`/settings/members?${qs(p)}`),
      invite: (i) => send('POST', '/settings/members/invite', { emails: i.emails, role: i.role }),
      setRole: (ids, role) => send('POST', '/settings/members/role', { ids, role }),
      remove: (ids) => send('POST', '/settings/members/delete', { ids }),
      options: (p) => get(`/settings/members/options?${optionsQs(p)}`),
    },
    invites: {
      get: async (token) => {
        const i = await get<PlatformInvite>(`/invites/${encodeURIComponent(token)}`);
        // The invitee sets a password only where their workspace signs in by password; an SSO workspace signs them in
        // through its provider afterwards, and the link alone signs them in now.
        const options = await signInOptions(i.email).catch(() => ({ password: true, sso: null }));
        const sso = !options.password && !!options.sso;
        return { ...i, role: ROLE_LABEL[i.role] ?? i.role, invitedBy: i.invitedBy ?? 'an admin', sso, ssoProviderLabel: options.sso?.label, mfaRequired: false, passwordless: sso };
      },
      accept: async (token, input) => {
        const session = await acceptInvite(token, input.name, input.password);
        const invite = await get<PlatformInvite>(`/invites/${encodeURIComponent(token)}`);
        return { email: session.user.email, name: session.user.name, team: invite.team, authMethod: 'session', next: '/' };
      },
    },
    audit: {
      list: async (p: ListParams<AuditFilters> & { view: AuditView }) => {
        const q = new URLSearchParams({ page: String(p.page), pageSize: String(p.pageSize), view: p.view });
        const kind = p.filters?.action?.[0];
        const target = p.filters?.targetType?.[0];
        if (kind) q.set('kind', kind);
        if (target) q.set('targetKind', target);
        const page = await get<ListResult<PlatformAuditRow> & { viewCounts: AuditViewCounts }>(`/audit?${q}`);
        return { ...page, data: page.data.map(entry) };
      },
    },
  };
}
