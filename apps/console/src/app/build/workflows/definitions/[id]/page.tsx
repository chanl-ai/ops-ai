'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { useCollapsedSidebar } from '@/components/shared/collapsed-sidebar';
import { LeaveGuard } from '@/components/shared/leave-guard';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DefinitionEditor } from '@/components/workflows/definition-editor/definition-editor';
import { SaveStateLine, workflowHeader } from '@/components/workflows/definition-editor/editor-shell';
import { useWorkingCopy } from '@/components/workflows/definition-editor/use-working-copy';
import { useCan, useCanBuild } from '@/hooks/me-queries';
import { useDefinition, useDefinitionChecks, useNodeTypes, usePublishWorkingCopy, useSetDefinitionPaused, useStartEngineRun, useStartWorkflow } from '@/hooks/engine-queries';
import type { DefinitionValidation, DefinitionView, EngineNodeType, OutdatedCopy } from '@/lib/types/engine';

const layout = {
  // The canvas fills what is left of the window under the header, so the page itself does not scroll.
  className: 'min-h-0 py-4 lg:py-4',
  contentClassName: 'flex min-h-0 flex-col gap-3',
};

export default function WorkflowDefinitionPage() {
  const { id } = useParams<{ id: string }>();
  const definition = useDefinition(id);
  const nodeTypes = useNodeTypes();
  // The canvas needs the width; the sidebar comes back as it was when the person leaves the page.
  useCollapsedSidebar();
  const header = { ...workflowHeader(id, definition.data), ...layout };

  if (definition.data && nodeTypes.data && !definition.isError) return <CanvasTab view={definition.data} types={nodeTypes.data} />;
  return (
    <PageLayout {...header}>
      {definition.isPending || nodeTypes.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} showToolbar />
      ) : definition.isError ? (
        <QueryError what="this workflow" error={definition.error} back={{ label: 'Back to workflows', href: '/build/workflows' }} onRetry={() => definition.refetch()} retrying={definition.isFetching} />
      ) : (
        nodeTypes.isError && <QueryError what="step types" error={nodeTypes.error} onRetry={() => nodeTypes.refetch()} retrying={nodeTypes.isFetching} />
      )}
    </PageLayout>
  );
}

/**
 * The canvas over the workflow's working copy: every change saves itself a second later without making a version,
 * the header says where the save stands and how many problems remain, and leaving with a change not yet saved asks
 * first. Publish makes the version.
 */
function CanvasTab({ view, types }: { view: DefinitionView; types: EngineNodeType[] }) {
  const id = view.workflowId;
  const router = useRouter();
  const canBuild = useCanBuild('workflows');
  const canPublish = useCan('workflows', 'publish');
  // A copy made on a version older than one saved outside the editor since is kept: nothing saves over it until the
  // person chooses to start from the newer version, and they may open their copy read-only to copy their changes out.
  const [startedFresh, setStartedFresh] = React.useState(false);
  const [showingMine, setShowingMine] = React.useState(false);
  const outdated = canBuild && !startedFresh ? (view.outdatedCopy ?? null) : null;
  const mine = outdated && showingMine ? outdated : null;
  const copy = useWorkingCopy(view, canBuild && !outdated);
  // Before the first change there is no working copy, so the stored version's checks are read once.
  const stored = useDefinitionChecks(view.workingCopy ? undefined : view.definition, view.digest);
  const checks = copy.checks ?? view.workingCopy?.checks ?? null;
  const validation: DefinitionValidation | null = checks ? { ok: !checks.some((c) => c.level === 'error'), workflowId: id, digest: null, checks } : (stored.data ?? null);
  const { mutateAsync: startAsync } = useStartEngineRun();
  const { mutateAsync: startByFormAsync } = useStartWorkflow();
  const { mutateAsync: publishAsync } = usePublishWorkingCopy(id);
  const { mutateAsync: pauseAsync, isPending: pausing } = useSetDefinitionPaused(id);
  const header = { ...workflowHeader(id, view, { liveChip: false }), ...layout };
  // The canvas opens on the copy read when the page opened (or reloaded). A save puts the saved copy in the cache;
  // handing it back to the editor would lay the steps out again and remount it, closing the open step mid-edit.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const opened = React.useMemo(() => mine?.definition ?? view.workingCopy?.definition ?? view.definition, [copy.revision, !!mine]);

  const startRun = React.useCallback(
    async (input: Record<string, unknown>, mode: 'live' | 'test') => {
      const run = await startAsync({ workflowId: id, input, mode });
      router.push(`/build/runs/${run.runId}`);
    },
    [startAsync, id, router],
  );
  const startByHand = React.useCallback(
    async (values: Record<string, unknown>, mode: 'live' | 'test') => {
      const run = await startByFormAsync({ workflowId: id, values, mode });
      router.push(`/build/runs/${run.runId}`);
    },
    [startByFormAsync, id, router],
  );
  // The publish reads the newest copy the cache holds, so a save that landed after the page opened is the one published.
  const viewRef = React.useRef(view);
  viewRef.current = view;
  const requestPublish = React.useCallback((note: string) => publishAsync({ view: viewRef.current, note }), [publishAsync]);

  return (
    <>
      <LeaveGuard unsaved={canBuild && copy.unsaved} failed={copy.state === 'failed'} />
      <DefinitionEditor
        key={`${id}-${copy.revision}-${mine ? 'mine' : 'newest'}`}
        definition={opened}
        types={types}
        validation={validation}
        validateError={stored.isError ? (stored.error as Error).message : null}
        onChange={copy.onChange}
        changed={!!view.workingCopy || copy.unsaved}
        saving={copy.unsaved}
        saveState={canBuild ? <SaveStateLine state={copy.state} savedAt={copy.savedAt} error={copy.error} onRetry={copy.retry} /> : undefined}
        startRun={startRun}
        startByHand={startByHand}
        lifecycle={view}
        requestPublish={requestPublish}
        setPaused={pauseAsync}
        pausing={pausing}
        readOnly={!canBuild || !!outdated}
        readOnlyNote={outdated ? 'Nothing is saved until you choose below.' : undefined}
        canPublish={canPublish}
        frame={({ actions, canvas }) => (
          <PageLayout {...header} actions={actions}>
            {outdated && (
              <Alert data-testid="definition-outdated-copy">
                <AlertTitle>A newer version was saved outside the editor</AlertTitle>
                <AlertDescription>
                  <p>
                    {outdatedNote(outdated)} Reload to start from it, or copy your changes first. {mine ? 'You are looking at your copy; it cannot be edited.' : `You are looking at version ${outdated.newerVersion}.`}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => setShowingMine((v) => !v)} data-testid="definition-outdated-open">
                      {mine ? `Show version ${outdated.newerVersion}` : 'Open my copy'}
                    </Button>
                    <Button size="sm" onClick={() => (setShowingMine(false), setStartedFresh(true))} data-testid="definition-outdated-reload">
                      Reload to start from version {outdated.newerVersion}
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}
            {copy.stale && (
              <Alert data-testid="definition-stale">
                <AlertTitle>Your change was not saved</AlertTitle>
                <AlertDescription>
                  <p>{copy.stale} Nothing more is saved from this page until you reload. Reloading shows their copy; your unsaved change on this page is dropped.</p>
                  <Button variant="outline" size="sm" className="mt-2" onClick={() => void copy.reload()} disabled={copy.reading} data-testid="definition-stale-reload">
                    Reload their copy
                  </Button>
                </AlertDescription>
              </Alert>
            )}
            {canvas}
          </PageLayout>
        )}
      />
    </>
  );
}

/** Who saved the newer version and when, for the outdated copy's notice. */
function outdatedNote(c: OutdatedCopy): string {
  const at = c.newerAt ? new Date(c.newerAt) : null;
  const when = at && !Number.isNaN(at.getTime()) ? ` at ${at.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}` : '';
  return `${c.newerBy || 'Someone'} saved version ${c.newerVersion}${when}; your unpublished changes, made on version ${c.baseVersion}, are kept.`;
}
