'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { AlertTriangle, Bot, Coins, KeyRound, Plus, ShieldCheck, UserPlus } from 'lucide-react';
import { toast } from 'sonner';

import { GrantDialog } from '@/components/access/grant-dialog';
import { RoleDialog } from '@/components/access/role-dialog';
import { PageLayout } from '@/components/page-layout';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAccessOptions, useAssignRole, useGrantAccess, useIdentities } from '@/hooks/governance-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { useTeam } from '@/hooks/use-team';
import { count } from '@/lib/format';

import { GrantsTab } from './_parts/grants-tab';
import { IdentitiesTab } from './_parts/identities-tab';
import { RolesTab } from './_parts/roles-tab';

const TABS = ['identities', 'grants', 'roles'] as const;

export default function AccessPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [tab, setTab] = useTabParam(TABS, 'identities');
  const workflowId = params.get('workflow') ?? undefined;
  const { team, teams, teamId } = useTeam();
  // Same params as the identities tab's first page, so this shares its request.
  const summary = useIdentities({ page: 1, pageSize: 10, filters: {} });
  const opts = useAccessOptions();
  const grant = useGrantAccess();
  const assign = useAssignRole();
  const [grantOpen, setGrantOpen] = React.useState(false);
  const [roleOpen, setRoleOpen] = React.useState(false);
  const stats = summary.data?.stats;

  const openIdentity = React.useCallback((wid: string) => router.replace(`${pathname}?tab=grants&workflow=${wid}`, { scroll: false }), [router, pathname]);
  const clearWorkflow = React.useCallback(() => {
    const next = new URLSearchParams(params.toString());
    next.delete('workflow');
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }, [params, router, pathname]);

  return (
    <PageLayout
      icon={ShieldCheck}
      title="Access"
      description="What each workflow can reach, and who can author, approve and publish"
      actions={
        tab === 'roles' ? (
          <Button onClick={() => setRoleOpen(true)}>
            <UserPlus className="size-4" /> Add people or group
          </Button>
        ) : (
          <Button onClick={() => setGrantOpen(true)}>
            <Plus className="size-4" /> Grant access
          </Button>
        )
      }
    >
      <div className="flex flex-col gap-4">
        <StatCardGrid columns={4}>
          <StatCard label="Workflow identities" value={stats ? count(stats.identities) : undefined} loading={summary.isPending} icon={Bot} footer={{ text: 'One per workflow', subtext: 'Used at the data and AI gateways' }} />
          <StatCard label="Active grants" value={stats ? count(stats.activeGrants) : undefined} loading={summary.isPending} icon={KeyRound} footer={{ text: 'Modules and knowledge bases', subtext: 'Expired grants not counted' }} />
          <StatCard label="Expiring in 14 days" value={stats ? count(stats.expiringSoon) : undefined} loading={summary.isPending} icon={AlertTriangle} footer={{ text: stats?.expiringSoon ? 'Extend or let lapse' : 'Nothing expiring', subtext: 'See Expiring soon under Grants' }} />
          <StatCard label="Money-movement grants" value={stats ? count(stats.moneyMovementGrants) : undefined} loading={summary.isPending} icon={Coins} footer={{ text: 'Always expire within 180 days', subtext: 'Every call still needs approval' }} />
        </StatCardGrid>

        <Tabs value={tab} onValueChange={(v) => setTab(v as (typeof TABS)[number])}>
          <TabsList>
            <TabsTrigger value="identities">Workflow identities</TabsTrigger>
            <TabsTrigger value="grants">Grants</TabsTrigger>
            <TabsTrigger value="roles">Author, approve, publish</TabsTrigger>
          </TabsList>
          <TabsContent value="identities" className="mt-4">
            <IdentitiesTab onOpen={openIdentity} />
          </TabsContent>
          <TabsContent value="grants" className="mt-4">
            <GrantsTab workflowId={workflowId} onClearWorkflow={clearWorkflow} />
          </TabsContent>
          <TabsContent value="roles" className="mt-4">
            <RolesTab team={team} teams={teams} />
          </TabsContent>
        </Tabs>
      </div>

      <GrantDialog
        open={grantOpen}
        onOpenChange={setGrantOpen}
        options={opts.data}
        defaultWorkflowId={workflowId}
        isPending={grant.isPending}
        onSubmit={async (input) => {
          const g = await grant.mutateAsync(input);
          toast.success(`Granted ${g.workflowName} access to ${g.resource}`);
        }}
      />
      <RoleDialog
        open={roleOpen}
        onOpenChange={setRoleOpen}
        options={opts.data}
        currentTeamId={teamId}
        canPickTeam={team?.scope === 'all'}
        isPending={assign.isPending}
        onSubmit={async (input) => {
          const r = await assign.mutateAsync(input);
          toast.success(`${r.principal} can ${r.capabilities.join(', ')} in ${r.team}`);
        }}
      />
    </PageLayout>
  );
}
