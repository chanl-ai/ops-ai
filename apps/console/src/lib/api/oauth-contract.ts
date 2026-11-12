import type { ConnectedAssistant, OAuthConsent, OAuthRequest } from '@/lib/types/oauth';

/**
 * Connecting an assistant to a team's MCP address. The consent page and the person's own connections; the
 * assistant's side (register, authorize, token) is the authorization server's and has no console client.
 */
export interface OAuthApi {
  /** What the consent page shows. 400 when the request is not one this install can honour, 403 `team_forbidden` for a person outside the address's team. */
  consent(request: OAuthRequest): Promise<OAuthConsent>;
  /** The person's answer. Returns where to send the browser: back to the assistant with a code, or with `access_denied`. */
  decide(request: OAuthRequest, decision: 'allow' | 'deny'): Promise<{ redirectTo: string }>;
  /** The signed-in person's live connections, newest first. */
  grants(): Promise<ConnectedAssistant[]>;
  /** Ends one of the person's connections; the assistant cannot renew. */
  disconnect(id: string): Promise<void>;
}
