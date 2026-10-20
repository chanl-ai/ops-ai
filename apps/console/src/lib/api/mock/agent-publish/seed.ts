/**
 * Seed for agent publishing. Every other agent's newest version is published. Mortgage Intake has a draft one
 * version ahead of what workflows pin; Branch Concierge's draft is waiting in Reviews, saved and requested by someone
 * other than the demo user so the demo user can approve it.
 */
export const AGENT_PUBLISH_SEED: Record<string, { behind: number; never?: boolean; openReview?: { by: string; note: string; minutesAgo: number } }> = {
  ag_loan: { behind: 1 },
  // Advisor Copilot has only ever had drafts.
  ag_advisor: { behind: 0, never: true },
  ag_branch: { behind: 1, openReview: { by: 'Maya Okafor', note: 'Answer holiday branch hours from the Retail banking calendar', minutesAgo: 95 } },
};

/** The version workflows pin at seed time: null for agents that were never marked ready. */
export const seedPublished = (a: { id: string; version: number }): number | null => (AGENT_PUBLISH_SEED[a.id]?.never ? null : a.version - (AGENT_PUBLISH_SEED[a.id]?.behind ?? 0));
