'use client';

import * as React from 'react';
import { Info, Lock } from 'lucide-react';
import { toast } from 'sonner';

import { PublishModeEditor } from '@/components/settings/publish-mode-editor';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Note } from '@/components/shared/setting/note';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePolicyEditor, useSetWorkspacePolicy, useWorkspacePolicies } from '@/hooks/policy-queries';
import { useTeam } from '@/hooks/use-team';
import { ApiError } from '@/lib/api/contract';

/**
 * Publish reviews: which of the acting team's publishes need a second person, area by area. It reads and writes the
 * publishReview policy (GET and PUT /v1/policies/publishReview, c-214); the value is the team's own `{ area: mode }`.
 */
export default function PublishReviewsPage() {
  const { team } = useTeam();
  const teamId = team?.id ?? '';
  const policies = useWorkspacePolicies();
  const editor = usePolicyEditor();
  const set = useSetWorkspacePolicy();
  const refusedRead = policies.error instanceof ApiError && policies.error.status === 403;
  const [stored, setStored] = React.useState<Record<string, string> | null>(null);
  const policy = policies.data?.find((p) => p.key === 'publishReview');
  const saved = React.useMemo(() => stored ?? (((policy?.value as Record<string, Record<string, string>> | null | undefined)?.[teamId] ?? {}) as Record<string, string>), [policy, teamId, stored]);
  const [draft, setDraft] = React.useState<Record<string, string>>(saved);
  React.useEffect(() => {
    setDraft(saved);
  }, [saved]);
  const cell = policy?.changedBy ?? 'reviews.manage';
  const roles = editor.data?.cells[cell] ?? [];
  const canEdit = !!policy && policy.changedBy in (editor.data?.cells ?? {});
  const save = async () => {
    try {
      const out = await set.mutateAsync({ key: 'publishReview', value: draft, teamId });
      setStored(((out.value as Record<string, Record<string, string>>)?.[teamId] ?? draft) as Record<string, string>);
      toast.success('Saved publish reviews', { description: 'New publishes follow it. Reviews already open keep the rule they were opened under.' });
    } catch (e) {
      toast.error('Couldn’t save publish reviews', { description: (e as Error).message });
    }
  };
  return (
    <SettingsPageLayout section="Publish reviews" description={`Which publishes in ${team?.name ?? 'this team'} need a second person to approve them.`}>
      {policies.isPending || editor.isPending ? (
        <Skeleton className="h-64 w-full" aria-busy="true" />
      ) : refusedRead ? (
        // Reading policies needs settings.view; the server's refusal names the role and who holds it.
        <EmptyState icon={Lock} title="You can’t see publish reviews" description={(policies.error as Error).message} testId="publish-reviews-refused" />
      ) : (policies.isError && !refusedRead) || !policy ? (
        <QueryError what="publish reviews" error={policies.error} onRetry={() => policies.refetch()} retrying={policies.isFetching} />
      ) : (
        <>
          <Note title="What counts as a major change">A first publish, and any change to approval rules, access, egress or a guardrail. Under Publish at once, a publish goes live and records who published it, except a change to a guardrail, an approval rule, access or egress, which still needs a review.</Note>
          <SettingCard
            id="publish-review"
            title="Review before publishing"
            description={policy?.effect ?? 'Which of a team’s publishes wait for review: always, major changes only (the default), or never.'}
            help={`Default: Review major changes${roles.length ? ` · Changed by ${roles.join(', ')}` : ''}`}
            onSave={save}
            saving={set.isPending}
            dirty={JSON.stringify(draft) !== JSON.stringify(saved)}
            locked={!canEdit}
            requiredRole={roles.join(' or ') || undefined}
          >
            <PublishModeEditor value={draft} onChange={setDraft} disabled={!canEdit} />
          </SettingCard>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Info className="size-3.5" /> Who decides at each gate is set under Gate policies.
          </p>
        </>
      )}
    </SettingsPageLayout>
  );
}
