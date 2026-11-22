'use client';

import { PublishDialog } from '@/components/shared/publish-dialog';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { Skeleton } from '@/components/ui/skeleton';
import { useWorkflowPublishPreview } from '@/hooks/engine-queries';
import type { WorkflowPublishPreview } from '@/lib/types/engine';

import { ChangesList } from './changes-list';
import { canSubmitPublish } from './publish-state';

/** What happens once Publish is pressed, from the team's publish policy as the server read it. */
function nextStep(p: WorkflowPublishPreview): string {
  if (p.reviewRequired) return 'Needs approval from another person in Reviews before it goes live.';
  if (p.reviewReason === 'minor_change') return 'Only step positions or the workflow name changed: goes live at once.';
  return 'Your team publishes without a review: goes live at once.';
}

/**
 * Publishes the working copy: makes the next version from it and opens its review, or puts it live at once where the
 * team's policy needs none. It lists what changed against the live version and every problem the server would refuse
 * the publish on (the same list the publish checks); Publish and Send for review stay disabled while one remains.
 */
export function PublishDefinitionDialog({
  open,
  onOpenChange,
  workflowId,
  nodeName,
  onFix,
  onRequest,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflowId: string;
  nodeName: (id: string) => string;
  /** Opens a step's settings, closing the dialog. */
  onFix: (nodeId: string) => void;
  onRequest: (note: string) => Promise<unknown>;
}) {
  const preview = useWorkflowPublishPreview(workflowId, open);
  const p = preview.data;

  return (
    <PublishDialog
      open={open}
      onOpenChange={onOpenChange}
      testId="definition-publish"
      title="Publish your changes"
      description={p ? (p.liveVersion ? `Makes the next version from your changes, to replace version ${p.liveVersion} for new runs. Runs under way keep their version.` : 'Makes the first version from your changes.') : undefined}
      blockers={p?.blockers ?? []}
      where={(b) => (b.node ? nodeName(b.node) : 'Whole workflow')}
      onJump={(b) => b.node && onFix(b.node)}
      loading={
        preview.isPending ? (
          <div className="flex flex-col gap-2" data-testid="definition-publish-loading">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : undefined
      }
      loadError={preview.isError ? <QueryError what="what this publish changes" error={preview.error} onRetry={() => preview.refetch()} retrying={preview.isFetching} /> : undefined}
      note={{ label: 'Note to the reviewer', hint: 'The reviewer reads this beside the steps that changed.', placeholder: 'e.g. Refunds over 100 now wait for a review', multiline: true, required: !!p?.reviewRequired, missing: 'Say what changed, for the reviewer' }}
      nextStep={p ? nextStep(p) : undefined}
      submitLabel={p?.reviewRequired ? 'Send for review' : 'Publish'}
      submittingLabel="Publishing…"
      submitTestId="definition-publish-submit"
      disabled={!canSubmitPublish(p, false)}
      onSubmit={async (note) => {
        try {
          await onRequest(note);
        } catch (e) {
          void preview.refetch();
          throw e;
        }
      }}
    >
      {p && (
        <Section title="What changed" description={p.liveVersion ? `Against version ${p.liveVersion}, the live one` : 'Every step is new'} flush>
          <ChangesList diff={p.changes} />
        </Section>
      )}
    </PublishDialog>
  );
}
