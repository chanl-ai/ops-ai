'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Copy, Pencil, ShieldCheck, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { RoleDialog } from '@/components/access/role-dialog';
import { RoleGrid } from '@/components/access/role-grid';
import { PageLayout } from '@/components/page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { Row, Rows } from '@/components/shared/surface';
import { TeamName } from '@/components/shared/team-name';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateRole, useEditRole, useManagesRoles, useRole, useRoleChanges, useRoleHolders, useRoles } from '@/hooks/me-queries';
import { plural } from '@/lib/format';
import type { RoleCell, RoleDetail } from '@/lib/types/settings';

type Grid = RoleDetail['grid'];

const cellsOf = (grid: Grid): RoleCell[] =>
  grid.flatMap((row) => Object.entries(row.actions).flatMap(([action, scope]) => (scope ? [{ area: row.area, action, scope }] : [])));

/**
 * A role's grid: one row per area, one column per action, each cell All, Own or empty. A workspace admin ticks and
 * unticks cells and saves them; every service follows on each holder's next request. A built-in role can go back to
 * its default; Admin holds every cell and is not edited. A workspace admin copies any role, and renames or deletes a
 * custom one, moving the people who hold it to another role.
 */
export default function RolePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const role = useRole(id);
  const all = useRoles();
  const { save, reset } = useEditRole(id);
  const { rename, remove } = useRoleChanges(id);
  const create = useCreateRole();
  const manages = useManagesRoles();
  const r = role.data;
  const [dialog, setDialog] = React.useState<'copy' | 'rename' | 'delete' | null>(null);
  const holders = useRoleHolders(id, dialog === 'delete');
  const [moveTo, setMoveTo] = React.useState('');
  const others = (all.data ?? []).filter((x) => x.id !== id);
  const [draft, setDraft] = React.useState<Grid | null>(null);
  const [resetting, setResetting] = React.useState(false);
  React.useEffect(() => {
    setDraft(null);
  }, [r]);
  const grid = draft ?? r?.grid ?? [];
  const changed = !!draft && JSON.stringify(cellsOf(draft)) !== JSON.stringify(cellsOf(r?.grid ?? []));
  const toggle = React.useCallback(
    (area: string, action: string, on: boolean) =>
      setDraft((d) =>
        (d ?? r?.grid ?? []).map((row) =>
          row.area === area ? { ...row, actions: { ...row.actions, [action]: on ? (r?.grid.find((x) => x.area === area)?.actions[action] ?? 'all') : null } } : row,
        ),
      ),
    [r],
  );
  const kind = r ? (r.builtin ? (r.canEdit ? 'Built in' : 'Built in · read-only') : r.canEdit ? 'Custom' : 'Custom · read-only') : '';
  return (
    <PageLayout
      icon={ShieldCheck}
      title={r?.name ?? 'Role'}
      description={r?.description}
      backHref="/govern/access/roles"
      badge={
        r && (
          <>
            <Badge variant="outline" data-testid="role-kind">
              {kind}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {plural(r.permissionCount, 'permission')} · held by {r.assignmentCount}
            </span>
          </>
        )
      }
      actions={
        r && manages ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setDialog('copy')} data-testid="role-copy">
              <Copy className="size-4" />
              Copy
            </Button>
            {r.builtin && r.canEdit && (
              <Button variant="outline" size="sm" onClick={() => setResetting(true)} data-testid="role-reset">
                Reset to default
              </Button>
            )}
            {!r.builtin && (
              <>
                <Button variant="outline" size="sm" onClick={() => setDialog('rename')} data-testid="role-rename">
                  <Pencil className="size-4" />
                  Rename
                </Button>
                <Button variant="outline" size="sm" onClick={() => (setMoveTo(''), setDialog('delete'))} data-testid="role-delete">
                  <Trash2 className="size-4" />
                  Delete
                </Button>
              </>
            )}
          </div>
        ) : undefined
      }
    >
      {role.isPending ? (
        <PageSkeleton statCards={0} tableRows={10} showToolbar={false} />
      ) : role.isError || !r ? (
        <QueryError what="the role" error={role.error} onRetry={() => role.refetch()} retrying={role.isFetching} />
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {r.canEdit
              ? `Tick what this role allows. All: every record in the team. Own: only records the person created or was assigned. A change applies to everyone holding the role on their next action.${r.builtin ? '' : ' Secrets, egress and Security-team permissions come only with a built-in role.'}`
              : `All: every record in the team. Own: only records the person created or was assigned. Empty: not allowed. ${r.lockedReason ?? ''}`}
          </p>
          <RoleGrid grid={grid} onToggle={r.canEdit ? toggle : undefined} notHeld={r.notHeld} />
          {r.canEdit && (
            <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-background py-3">
              <Button variant="outline" disabled={!changed || save.isPending} onClick={() => setDraft(null)} data-testid="role-discard">
                Discard
              </Button>
              <LoadingButton
                disabled={!changed}
                isLoading={save.isPending}
                onClick={() =>
                  save.mutate(cellsOf(grid), {
                    onSuccess: () => toast.success(`Saved ${r.name}`),
                    onError: (e) => toast.error(`Couldn’t save ${r.name}`, { description: e.message }),
                  })
                }
                data-testid="role-save"
              >
                Save changes
              </LoadingButton>
            </div>
          )}
        </div>
      )}
      {r && (
        <RoleDialog
          open={dialog === 'copy' || dialog === 'rename'}
          onOpenChange={(o) => !o && setDialog(null)}
          roles={all.data ?? []}
          role={dialog === 'rename' ? r : null}
          copyOf={dialog === 'copy' ? r.id : null}
          pending={create.isPending || rename.isPending}
          onSubmit={(input) =>
            dialog === 'rename'
              ? rename.mutateAsync({ name: input.name, description: input.description }).then(() => toast.success(`Renamed to ${input.name}`))
              : create.mutateAsync(input).then((made) => {
                  toast.success(`Created ${made.name}`, made.leftOut.length ? { description: `Left out ${made.leftOut.length} secrets, egress and Security-team permissions: only a built-in role holds them.` } : undefined);
                  router.push(`/govern/access/roles/${encodeURIComponent(made.id)}`);
                })
          }
        />
      )}
      {r && !r.builtin && (
        <DeleteDialog
          open={dialog === 'delete'}
          onOpenChange={(o) => !o && setDialog(null)}
          entityType="role"
          entityName={r.name}
          testIdPrefix="role"
          isLoading={remove.isPending}
          description={
            holders.data?.length
              ? `${holders.data.length === 1 ? 'One person holds' : `${holders.data.length} people hold`} this role. Choose the role they move to, so nobody loses their access.`
              : 'Nobody holds this role. Deleting it is kept in the audit log.'
          }
          onConfirm={() => {
            if (holders.data?.length && !moveTo) {
              toast.error('Choose the role its holders move to first.');
              return;
            }
            return remove.mutateAsync(moveTo || undefined).then(
              () => {
                setDialog(null);
                toast.success(`Deleted ${r.name}`);
                router.push('/govern/access/roles');
              },
              (e: Error) => {
                toast.error(`Couldn’t delete ${r.name}`, { description: e.message });
              },
            );
          }}
        >
          {!!holders.data?.length && (
            <div className="flex flex-col gap-3" data-testid="role-holders">
              <Rows className="max-h-40 overflow-auto rounded-md border">
                {holders.data.map((h) => (
                  <Row key={`${h.id}-${h.teamId}`} title={h.name} description={h.email ?? undefined} trailing={h.teamId === '*' ? 'Every team' : <TeamName teamId={h.teamId} />} />
                ))}
              </Rows>
              <Select value={moveTo} onValueChange={setMoveTo}>
                <SelectTrigger aria-label="Move them to" data-testid="role-move-to">
                  <SelectValue placeholder="Move them to…" />
                </SelectTrigger>
                <SelectContent>
                  {others.map((o) => (
                    <SelectItem key={o.id} value={o.id}>
                      {o.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </DeleteDialog>
      )}
      {r && (
        <ConfirmActionDialog
          open={resetting}
          onOpenChange={setResetting}
          title={`Reset ${r.name} to its default`}
          consequence={`Every permission of ${r.name} goes back to the ones it ships with, for everyone who holds it.`}
          runsNow
          note="Your changes to this role are kept in the audit log."
          confirmLabel="Reset to default"
          isPending={reset.isPending}
          onConfirm={() =>
            reset.mutateAsync().then(
              () => {
                setResetting(false);
                toast.success(`${r.name} is back to its default`);
              },
              (e: Error) => toast.error(`Couldn’t reset ${r.name}`, { description: e.message }),
            )
          }
        />
      )}
    </PageLayout>
  );
}
