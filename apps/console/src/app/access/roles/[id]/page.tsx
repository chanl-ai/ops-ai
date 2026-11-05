'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { RoleGrid } from '@/components/access/role-grid';
import { PageLayout } from '@/components/page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useEditRole, useRole } from '@/hooks/me-queries';
import { plural } from '@/lib/format';
import type { RoleCell, RoleDetail } from '@/lib/types/settings';

type Grid = RoleDetail['grid'];

const cellsOf = (grid: Grid): RoleCell[] =>
  grid.flatMap((row) => Object.entries(row.actions).flatMap(([action, scope]) => (scope ? [{ area: row.area, action, scope }] : [])));

/**
 * A role's grid: one row per area, one column per action, each cell All, Own or empty. A workspace admin ticks and
 * unticks cells and saves them; every service follows once people's sign-ins refresh. A built-in role can go back to
 * its default. Admin holds every cell and is not edited.
 */
export default function RolePage() {
  const { id } = useParams<{ id: string }>();
  const role = useRole(id);
  const { save, reset } = useEditRole(id);
  const r = role.data;
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
      backHref="/access/roles"
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
        r?.canEdit && r.builtin ? (
          <Button variant="outline" size="sm" onClick={() => setResetting(true)} data-testid="role-reset">
            Reset to default
          </Button>
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
              ? 'Tick what this role allows. All: every record in the team. Own: only records the person created or was assigned. A change applies to everyone holding the role when their sign-in next refreshes, within 15 minutes.'
              : `All: every record in the team. Own: only records the person created or was assigned. Empty: not allowed. ${r.lockedReason ?? ''}`}
          </p>
          <RoleGrid grid={grid} onToggle={r.canEdit ? toggle : undefined} />
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
