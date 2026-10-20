'use client';

import * as React from 'react';
import Link from 'next/link';
import { ShieldCheck, UserPlus, Users } from 'lucide-react';

import { MembersPanel } from '@/components/access/members-panel';
import { PageLayout } from '@/components/page-layout';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useCan } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';
import { useWorkspaceTeamsEditor } from '@/hooks/workspace-team-queries';

/** Who is in the team and what each may do (c-077): one role per person per team, read from platform-service. */
export default function AccessPage() {
  const { team } = useTeam();
  // Undefined while the person's grants load: neither Invite nor its locked twin shows until the answer is known.
  const can = useCan('access', 'manage');
  const canManage = can === true;
  // Workspace admins also reach every team from here (c-198); the server decides who they are.
  const teamsEditor = useWorkspaceTeamsEditor();
  const [inviteOpen, setInviteOpen] = React.useState(false);
  return (
    <PageLayout
      icon={ShieldCheck}
      title="Members"
      switcher
      description={`Everyone in ${team?.name ?? 'this team'} and their role. ${can === undefined ? '' : canManage ? 'You invite people and change roles.' : 'People with Manage on Access invite and change roles; you read.'}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
            {teamsEditor.data?.canView && (
              <Button variant="outline" asChild>
                <Link href="/access/teams" data-testid="access-teams">
                  <Users className="size-4" /> Teams
                </Link>
              </Button>
            )}
            {canManage ? (
              <Button onClick={() => setInviteOpen(true)} data-testid="access-invite">
                <UserPlus className="size-4" /> Invite
              </Button>
            ) : can === false ? (
              // Shown, not hidden: a person who cannot invite reads why instead of looking for the button.
              <Tooltip>
                <TooltipTrigger asChild>
                  <span tabIndex={0} data-testid="access-invite-locked">
                    <Button disabled aria-describedby="invite-why">
                      <UserPlus className="size-4" /> Invite
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent id="invite-why">Inviting needs Manage on Access, which your role does not grant.</TooltipContent>
              </Tooltip>
            ) : null}
        </div>
      }
    >
      <MembersPanel inviteOpen={inviteOpen} onInviteOpenChange={setInviteOpen} />
    </PageLayout>
  );
}
