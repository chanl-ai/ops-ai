import type { AppCredential } from '@/hooks/systems-queries';

/** An app credential's page under Credentials, opened in the credential's own team. */
export const credentialHref = (c: Pick<AppCredential, 'id' | 'teamId'>) =>
  `/integrations/credentials/${encodeURIComponent(c.id)}?team=${encodeURIComponent(c.teamId)}`;

/** How a credential's client secret reads where it is shown: its last four characters, or that one is held. */
export function secretShown(c: { holdsSecret: boolean; secretEnds?: string | null }): string {
  if (!c.holdsSecret) return 'None yet';
  return c.secretEnds ? `Ends in ${c.secretEnds}` : 'Set';
}
