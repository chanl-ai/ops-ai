'use client';

import { toast } from 'sonner';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { useSetDefaultAgent } from '@/hooks/chat-queries';
import { useTeam } from '@/hooks/use-team';

/**
 * Confirms making `agent` the team's default (c-174): the settings dropdown, the agents list row and the agent page all
 * open this one dialog. agents-service refuses anyone but a team admin, so callers show it to team admins only.
 */
export function MakeDefaultAgentDialog({ agent, open, onOpenChange }: { agent?: { id: string; name: string }; open: boolean; onOpenChange: (open: boolean) => void }) {
  const set = useSetDefaultAgent();
  const { team } = useTeam();
  const teamName = team?.name ?? 'this team';
  if (!agent) return null;
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Make ${agent.name} the default for ${teamName}?`}
      consequence={`New chats in ${teamName} start on ${agent.name}, which can ask the team's other agents. Chats already open stay on their agent.`}
      runsNow
      note="Takes effect for the next chat. You can pick another default in General settings."
      confirmLabel="Make default"
      isPending={set.isPending}
      onConfirm={async () => {
        await set.mutateAsync(agent.id);
        toast.success(`${agent.name} is the default for ${teamName}`);
        onOpenChange(false);
      }}
    />
  );
}
