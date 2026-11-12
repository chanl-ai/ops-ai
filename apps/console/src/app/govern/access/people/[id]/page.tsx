'use client';

import { useParams } from 'next/navigation';
import * as React from 'react';
import { Plus, SearchCheck, User } from 'lucide-react';
import { toast } from 'sonner';

import { actionLabel, areaLabel, byActionOrder } from '@/components/access/access-words';
import { CheckAccessDialog } from '@/components/access/check-access-dialog';
import { GiveRoleDialog } from '@/components/access/give-role-dialog';
import { PageLayout } from '@/components/page-layout';
import { FieldRow } from '@/components/shared/field-row';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { Row, Rows, Section } from '@/components/shared/surface';
import { TeamName } from '@/components/shared/team-name';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useCan, usePersonPermissions, useRoleGrants, useRoles } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';
import type { EffectivePermission, RoleGrant } from '@/lib/types/settings';

/** A role in words: its name, and "(team)" when it was given to the person's team rather than to them. */
const roleWords = (r: EffectivePermission['roles'][number]) => `${r.name}${r.via === 'team' ? ' (team)' : ''}`;
/** Each granting role once, in the order first met: "Admin, Security admin". */
const rolesOf = (held: EffectivePermission[]) => [...new Set(held.flatMap((p) => p.roles.map(roleWords)))].join(', ');

/** One scope's grants by area: each action with its scope, and the roles that grant them. */
function Grants({ permissions, testId }: { permissions: EffectivePermission[]; testId: string }) {
  const areas = [...new Set(permissions.map((p) => p.area))];
  if (!areas.length) return <p className="text-sm text-muted-foreground">Nothing here.</p>;
  return (
    <div className="flex flex-col divide-y" data-testid={testId}>
      {areas.map((area) => {
        const held = permissions.filter((p) => p.area === area).sort((a, b) => byActionOrder(a.action, b.action));
        return (
          // Area, its actions and where they come from on one row from sm up; stacked on a phone.
          <div key={area} className="grid gap-x-4 gap-y-1 py-2.5 sm:grid-cols-[10rem_minmax(0,1fr)_auto] sm:items-baseline" data-testid={`${testId}-${area}`}>
            <span className="text-sm font-medium">{areaLabel(area)}</span>
            <span className="flex flex-wrap gap-1.5">
              {held.map((p) => (
                <Badge key={p.action} variant="outline" className="font-normal" title={`Granted by ${p.roles.map(roleWords).join(', ')}`}>
                  {actionLabel(p.action)}
                  {p.scope === 'own' ? ' · own' : ''}
                </Badge>
              ))}
            </span>
            <span className="text-xs text-muted-foreground sm:text-right">from {rolesOf(held)}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * A person's access: what they may do in each team they share with you, and what they may do in every team
 * (a role assigned workspace-wide), each action with the role and the assignment that grant it. This is their
 * effective access, which can be more than their team role says.
 */
export default function PersonAccessPage() {
  const { id } = useParams<{ id: string }>();
  const q = usePersonPermissions(id);
  const p = q.data;
  const { team } = useTeam();
  // Checking someone's access is reading access in the team the console acts in.
  const canCheck = useCan('access', 'view') === true;
  // Giving a role is an admin's of the role's team; the service refuses anyone else and the dialog shows why.
  const canGive = useCan('access', 'manage') === true;
  const roles = useRoles();
  const { grants, give, take, available } = useRoleGrants(id);
  const [checking, setChecking] = React.useState(false);
  const [giving, setGiving] = React.useState(false);
  const [taking, setTaking] = React.useState<RoleGrant | null>(null);
  if (q.isPending) return <RecordSkeleton />;
  return (
    <PageLayout
      icon={User}
      title={p?.name ?? 'Person'}
      description={[p?.email, ...(p?.teams.map((t) => t.teamName) ?? [])].filter(Boolean).join(' · ') || undefined}
      backHref="/govern/access"
      actions={
        canCheck && p ? (
          <Button variant="outline" onClick={() => setChecking(true)} data-testid="check-access">
            <SearchCheck className="size-4" /> Check access
          </Button>
        ) : undefined
      }
    >
      {q.isError || !p ? (
        <QueryError what="this person's access" error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
      ) : (
        <RecordLayout
          rail={
            <AttributeCard title="Access" icon={User}>
              {p.teams.map((t) => (
                <FieldRow key={t.teamId} label={t.teamName} value={rolesOf(t.permissions) || 'No role'} wrap />
              ))}
              <FieldRow label="In every team" value={p.workspace.length ? rolesOf(p.workspace) : 'None'} wrap />
              <FieldRow label="Permissions" value={String(new Set([...p.workspace, ...p.teams.flatMap((t) => t.permissions)].map((x) => `${x.area}.${x.action}`)).size)} />
            </AttributeCard>
          }
        >
          <div className="flex flex-col gap-4">
            {available && (
              <Section
                title="Roles given"
                description="Workspace roles given to them in a team, on top of their team role."
                actions={
                  canGive ? (
                    <Button variant="outline" size="sm" onClick={() => setGiving(true)} data-testid="give-role">
                      <Plus className="size-4" /> Give a role
                    </Button>
                  ) : undefined
                }
              >
                {grants.data?.length ? (
                  <Rows testId="role-grants">
                    {grants.data.map((g) => (
                      <Row
                        key={g.id}
                        title={g.roleName}
                        description={<TeamName teamId={g.teamId} />}
                        trailing={
                          canGive ? (
                            <Button variant="ghost" size="sm" onClick={() => setTaking(g)} data-testid={`take-role-${g.id}`}>
                              Take away
                            </Button>
                          ) : undefined
                        }
                      />
                    ))}
                  </Rows>
                ) : (
                  <p className="text-sm text-muted-foreground">{grants.isPending ? 'Loading…' : 'None. Their access comes from their team roles.'}</p>
                )}
              </Section>
            )}
            {p.workspace.length > 0 && (
              <Section title="In every team" description="From a role assigned across the workspace; it applies in every team, whatever their team role.">
                <Grants permissions={p.workspace} testId="grants-workspace" />
              </Section>
            )}
            {p.teams.map((t) => (
              <Section key={t.teamId} title={`In ${t.teamName}`} description="From the roles they hold in this team. A missing action is not allowed.">
                <Grants permissions={t.permissions} testId={`grants-${t.teamId}`} />
              </Section>
            ))}
          </div>
        </RecordLayout>
      )}
      {p && (
        <GiveRoleDialog
          open={giving}
          onOpenChange={setGiving}
          personName={p.name ?? 'this person'}
          roles={roles.data ?? []}
          teamName={team?.name ?? 'this team'}
          pending={give.isPending}
          onSubmit={(input) => give.mutateAsync(input).then((g) => toast.success(`Gave ${p.name ?? 'them'} ${g.roleName}`))}
        />
      )}
      {taking && (
        <ConfirmActionDialog
          open={!!taking}
          onOpenChange={(o) => !o && setTaking(null)}
          title={`Take ${taking.roleName} away`}
          consequence={`${p?.name ?? 'They'} lose what ${taking.roleName} allows in this team on their next action; their team role stays.`}
          runsNow
          confirmLabel="Take away"
          isPending={take.isPending}
          onConfirm={() =>
            take.mutateAsync(taking.id).then(
              () => {
                setTaking(null);
                toast.success(`Took ${taking.roleName} away`);
              },
              (e: Error) => {
                toast.error(`Couldn’t take ${taking.roleName} away`, { description: e.message });
              },
            )
          }
        />
      )}
      {p && <CheckAccessDialog open={checking} onOpenChange={setChecking} personId={id} personName={p.name ?? 'this person'} teamName={team?.name ?? 'this team'} />}
    </PageLayout>
  );
}
