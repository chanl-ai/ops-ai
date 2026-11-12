import type { ConnectedAssistant, OAuthConsent } from '@/lib/types/oauth';

import { ApiError } from '../../contract';
import type { OAuthApi } from '../../oauth-contract';
import { notFound, respond } from '../runtime';

const HOUR = 3_600_000;
const ago = (h: number) => new Date(Date.now() - h * HOUR).toISOString();
const ahead = (h: number) => new Date(Date.now() + h * HOUR).toISOString();

/** Assistants connected to the demo person's teams, for the mock stack. */
export function createOAuthMock(): { api: OAuthApi } {
  let rows: ConnectedAssistant[] = [
    { id: 'ses_claude', clientId: 'cli_claude', clientName: 'Claude', teamId: 'team_ops', teamName: 'Platform', resource: 'https://ops.harborpine.example/mcp/team_ops', createdAt: ago(3), expiresAt: ahead(5), lastUsedAt: ago(0.2) },
    { id: 'ses_cursor', clientId: 'cli_cursor', clientName: 'Cursor', teamId: 'team_ops', teamName: 'Platform', resource: 'https://ops.harborpine.example/mcp/team_ops', createdAt: ago(30), expiresAt: ahead(2), lastUsedAt: ago(26) },
  ];
  const api: OAuthApi = {
    consent: (request) =>
      respond((m): OAuthConsent => {
        if (!request.client_id || !request.redirect_uri) throw new ApiError('That request is missing parts. Start again from your assistant.', 400);
        if (m === 'empty') throw new ApiError('You are not a member of that team.', 403, undefined, 'team_forbidden');
        const team = request.resource?.split('/mcp/')[1] ?? 'team_ops';
        return {
          client: { id: request.client_id, name: 'Claude', nameIsSelfReported: true },
          redirectHost: new URL(request.redirect_uri).hostname,
          team: { id: team, name: team === 'team_ops' ? 'Platform' : team },
          resource: request.resource ?? '',
          connectionHours: 8,
        };
      }),
    decide: (request, decision) => respond(() => ({ redirectTo: `${request.redirect_uri}?${decision === 'allow' ? 'code=mock' : 'error=access_denied'}${request.state ? `&state=${request.state}` : ''}` })),
    grants: () => respond((m) => (m === 'empty' ? [] : rows)),
    disconnect: (id) =>
      respond(() => {
        if (!rows.some((r) => r.id === id)) notFound('Connection');
        rows = rows.filter((r) => r.id !== id);
      }),
  };
  return { api };
}
