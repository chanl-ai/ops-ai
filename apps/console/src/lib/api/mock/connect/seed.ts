import type { IdentityAssurance } from '@/lib/types/connect';

/**
 * Seed for what only Connect holds: the assistants staff have connected and how busy each exposed workflow is
 * over MCP. Exposure itself is MCP deployments in the deployments store.
 */
export const MCP_URL = 'https://harborpine.ops-ai.app/mcp';

/** Workflows exposed over MCP at seed time, with their calls per day. */
export const SEED_EXPOSED: { workflowId: string; callsPerDay: number; daysAgo: number }[] = [
  { workflowId: 'wf_dispute', callsPerDay: 46, daysAgo: 40 },
  { workflowId: 'wf_kyb', callsPerDay: 21, daysAgo: 26 },
];

export const SEED_ASSISTANTS: { id: string; client: string; person: string; team: string; minutesAgo: number; calls: number; assurance: IdentityAssurance }[] = [
  { id: 'as_1', client: 'Claude Desktop', person: 'Maya Okafor', team: 'Card Services', minutesAgo: 14, calls: 512, assurance: 'attested' },
  { id: 'as_2', client: 'Microsoft Copilot (Teams)', person: 'Anika Singh', team: 'Onboarding', minutesAgo: 95, calls: 238, assurance: 'attested' },
  { id: 'as_3', client: 'Cursor', person: 'Daniel Brooks', team: 'Fraud Strategy', minutesAgo: 60 * 26, calls: 41, assurance: 'claimed' },
];

/** Calls per day a newly exposed workflow starts with in the mock, so a switch flip shows up in the numbers. */
export const NEW_EXPOSURE_CALLS_PER_DAY = 6;
