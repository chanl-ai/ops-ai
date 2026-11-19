'use client';

import { toast } from 'sonner';

import { SwitchRow } from '@/components/shared/setting/setting-row';
import { usePolicyEditor, useSetWorkspacePolicy, useWorkspacePolicies } from '@/hooks/policy-queries';
import { useTeam } from '@/hooks/use-team';

/** The team's list of apps whose writes run in chat without asking the person first (platform-service policy). */
const KEY = 'appsChangeWithoutAsking';

/**
 * One app's "Ask before changes" switch, on unless the team's admin listed the app in appsChangeWithoutAsking. While on,
 * each write the AI makes in this app pauses in chat for the person's Allow or Deny. Only someone holding the policy's
 * grid cell changes it; anyone else sees it read-only with who may.
 */
export function AskBeforeChanges({ appId, appName }: { appId: string; appName: string }) {
  const { team } = useTeam();
  const policies = useWorkspacePolicies();
  const editor = usePolicyEditor();
  const set = useSetWorkspacePolicy();
  const policy = policies.data?.find((p) => p.key === KEY);
  if (!policy || !team) return null;
  const byTeam = policy.value && typeof policy.value === 'object' && !Array.isArray(policy.value) ? (policy.value as Record<string, unknown>) : {};
  const listed = Array.isArray(byTeam[team.id]) ? (byTeam[team.id] as unknown[]).map(String) : [];
  const asks = !listed.includes(appId);
  const roles = editor.data?.cells?.[policy.changedBy] ?? [];
  const canChange = !!editor.data && policy.changedBy in (editor.data.cells ?? {});
  const change = (on: boolean) =>
    set.mutate(
      { key: KEY, value: on ? listed.filter((a) => a !== appId) : [...listed, appId], teamId: team.id },
      {
        onSuccess: () => toast.success(on ? `${appName} asks before changes` : `${appName} changes without asking`),
        onError: (e) => toast.error(`Couldn’t change ${appName}`, { description: e.message }),
      },
    );
  return (
    <SwitchRow
      id="ask-before-changes"
      label="Ask before changes"
      effect={`Before the AI changes anything in ${appName}, the person in the chat gets Allow or Deny. Test accounts never ask; workflows keep their own approvals.`}
      defaultLabel="On"
      role={roles.join(' or ') || 'Admin'}
      canChange={canChange && !set.isPending}
      checked={asks}
      onCheckedChange={change}
    />
  );
}
