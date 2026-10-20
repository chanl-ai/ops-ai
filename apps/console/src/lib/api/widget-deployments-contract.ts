import type { CreatedWidgetMintKey, WidgetDeployment, WidgetDeploymentInput, WidgetDeploymentPatch, WidgetMintKey } from '@/lib/types/widget-deployments';

/**
 * Widget deployments (c-117, c-118): an agent embedded on intranet pages. Builders and admins of the agent's team make
 * and change them; a deployment pins the agent's published version and lists exact origins. Sessions are minted by
 * the page from the person's SSO token, or by the bank's server with the deployment's own mint key (c-131); no key ever
 * goes in the snippet.
 */
export interface WidgetDeploymentsApi {
  list(agentId: string): Promise<WidgetDeployment[]>;
  create(input: WidgetDeploymentInput): Promise<WidgetDeployment>;
  /**
   * On the channel API (`/v1/channels/{id}`, c-245): a name, pause or origins change, or what it serves. An origins or
   * serves change follows the team's publish review, so it answers `{ reviewId }` while it waits. Retiring is its own call.
   */
  update(id: string, patch: WidgetDeploymentPatch): Promise<{ reviewId?: string }>;
  /** The deployment's mint keys, revoked ones included, newest first. */
  keys(id: string): Promise<WidgetMintKey[]>;
  /** `expiresInDays` from 1 to 365; the server's default is 90. */
  createKey(id: string, name: string, expiresInDays?: number): Promise<CreatedWidgetMintKey>;
  revokeKey(id: string, keyId: string): Promise<{ id: string; revoked: boolean }>;
  /** Where pages load the chat loader from: the embed app's `/embed/v1.js` (NEXT_PUBLIC_OPS_EMBED_URL), else the agents
   * service's own copy. The iframe it opens is on the same host. */
  /** A session for the signed-in builder, bound to the console's origin, for Preview as a person (c-232). */
  previewSession(id: string): Promise<{ session: string; expiresIn: number }>;
  scriptUrl(): string;
}
