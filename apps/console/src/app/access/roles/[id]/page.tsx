'use client';

import { useParams } from 'next/navigation';
import { ShieldCheck } from 'lucide-react';

import { RoleGrid } from '@/components/access/role-grid';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { useRole } from '@/hooks/me-queries';

/** A role's grid (c-150): one row per area, one column per action, each cell All, Own or empty. Built-ins are read-only. */
export default function RolePage() {
  const { id } = useParams<{ id: string }>();
  const role = useRole(id);
  const r = role.data;
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
              {r.builtin ? 'Built in · read-only' : 'Custom'}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {r.permissionCount} permissions · held by {r.assignmentCount}
            </span>
          </>
        )
      }
    >
      {role.isPending ? (
        <PageSkeleton statCards={0} tableRows={10} showToolbar={false} />
      ) : role.isError || !r ? (
        <QueryError what="the role" error={role.error} onRetry={() => role.refetch()} retrying={role.isFetching} />
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">All: every record in the team. Own: only records the person created or was assigned. Empty: not allowed.</p>
          <RoleGrid grid={r.grid} />
        </div>
      )}
    </PageLayout>
  );
}
