/** An assistant (Claude, Cursor, VS Code, ChatGPT) a person connects to a team's MCP address with their sign-in. */

/** What the consent page shows for one request, as the authorization server read it. */
export interface OAuthConsent {
  client: { id: string; name: string; /** The name is what the assistant called itself; nothing checks it. */ nameIsSelfReported: boolean };
  /** The place the browser returns to after the answer, as the person should read it. */
  redirectHost: string;
  team: { id: string; name: string };
  /** The MCP address the assistant is allowed to use. */
  resource: string;
  connectionHours: number;
}

/** The authorization request as the assistant sent it to the browser (the page's own query string). */
export type OAuthRequest = Record<string, string>;

/** One of the signed-in person's connected assistants. */
export interface ConnectedAssistant {
  id: string;
  clientId: string;
  clientName: string;
  teamId: string;
  teamName: string;
  resource: string;
  createdAt: string;
  expiresAt: string;
  /** Null until the assistant first calls the address. */
  lastUsedAt: string | null;
}
