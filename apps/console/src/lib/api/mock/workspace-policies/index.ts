import type { WorkspacePoliciesApi } from '../../workspace-policies-contract';
import type { PolicyValue, WorkspacePolicy } from '@/lib/types/workspace-policies';

const SEED: WorkspacePolicy[] = [
  { key: 'requesterMayDecide', value: true, default: true, changedBy: 'settings.manage', effect: 'The person who asked for a decision may also make it. Off: someone else has to decide.' },
  { key: 'extractionFloor', value: 0.8, default: 0.8, changedBy: 'settings.manage', effect: 'The lowest confidence an Extract from file step may accept; no step can ask for less.' },
  { key: 'stepUp', value: false, default: false, changedBy: 'settings.manage', effect: 'Every approver confirms their sign-in again before deciding. Off: only operations that ask for it.' },
  { key: 'publishReview', value: {}, default: {}, changedBy: 'reviews.manage', effect: "Which of a team's publishes wait for review: always, major changes only (the default), or never." },
  { key: 'chatThreadsOwnerOnly', value: true, default: true, changedBy: 'settings.manage', effect: "Each chat thread is read only by the person who started it. Off: the team's admins read them too." },
  { key: 'memoryRetentionDays', value: null, default: null, changedBy: 'chat.manage', effect: 'How long agents keep what they remember about each person. Unset: kept until the person removes it.' },
  { key: 'reviewSlaHours', value: 8, default: 8, changedBy: 'reviews.manage', effect: 'How long a publish review may wait, in wall-clock hours, before it shows as overdue.' },
  { key: 'securityTeamAddsSecrets', value: false, default: false, changedBy: 'settings.manage', effect: "Only the security team adds secrets. Off: builders add and use their own team's secrets." },
];

/** Sample policies for a console with no platform-service: a page over them says so and stores nothing. */
export function createMockWorkspacePolicies(): WorkspacePoliciesApi {
  const rows = SEED.map((p) => ({ ...p }));
  return {
    list: async () => rows.map((p) => ({ ...p })),
    set: async (key: string, value: PolicyValue, teamId = 'team_ops') => {
      const row = rows.find((p) => p.key === key);
      if (!row) throw new Error(`${key} is not a policy`);
      // publishReview keeps one map per team and a save replaces the acting team's part only, as the server does.
      row.value = key === 'publishReview' ? { ...(row.value as Record<string, unknown>), [teamId]: value } : value;
      return { ...row };
    },
    editor: async () => ({ cells: { 'settings.manage': ['Security admin'], 'reviews.manage': ['Security admin'], 'chat.manage': ['Security admin'] } }),
  };
}
