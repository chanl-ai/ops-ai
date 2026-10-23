'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { CircleStop, Workflow } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { FieldRow } from '@/components/shared/field-row';
import { MiddleTruncate } from '@/components/shared/setting/middle-truncate';
import { CopyIconButton, CopyId } from '@/components/shared/setting/copy-field';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { ReadableValue } from '@/components/shared/readable-value';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { RunCanvas } from '@/components/workflows/run-canvas';
import { RunStoryView } from '@/components/workflows/run-story';
import { StoryFeed } from '@/components/workflows/story-feed';
import { StartedBy } from '@/components/workflows/started-by';
import { RunStatus } from '@/components/workflows/run-journal/run-status';
import { StepSheet } from '@/components/workflows/run-journal/step-sheet';
import { StepsTable } from '@/components/workflows/run-journal/steps-table';
import { TERMINAL_RUN, useCancelEngineRun, useDefinition, useEngineRun, useNodeTypes } from '@/hooks/engine-queries';
import { relativeTime } from '@/lib/format';

/** An engine word ("not_matched", "approve") as a person reads it ("Not matched", "Approve"). */
const words = (w: string) => w.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase());

/** One run of a v2 workflow, from the runner's journal: its steps with input, output, port, attempts and errors. */
export default function EngineRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const query = useEngineRun(runId);
  const run = query.data;
  // The definition the run is pinned to names its nodes.
  const definition = useDefinition(run?.workflowId ?? '', run?.version);
  const names = React.useMemo(() => new Map((definition.data?.definition.nodes ?? []).map((n) => [n.id, n.name || n.id])), [definition.data]);
  const nodeName = React.useCallback((id: string) => names.get(id) ?? id, [names]);
  const [open, setOpen] = React.useState<number | null>(null);
  const nodeTypes = useNodeTypes();
  const cancel = useCancelEngineRun();
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [cancelError, setCancelError] = React.useState<string>();
  // The run that started it (`run:<id>`). The runs it started and the files it was given come with the run.
  const parentRun = run?.createdBy.startsWith('run:') ? run.createdBy.slice(4) : undefined;
  const files = run?.files ?? [];

  if (query.isPending)
    return (
      <PageLayout icon={Workflow} title="Run" backHref="/workflows/runs">
        <PageSkeleton statCards={4} tableRows={6} showToolbar={false} />
      </PageLayout>
    );
  if (query.isError || !run)
    return (
      <PageLayout icon={Workflow} title="Run" backHref="/workflows/runs">
        <QueryError what="this run" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      </PageLayout>
    );

  const step = open === null ? null : (run.steps[open] ?? null);
  const told = !!run.story && (!!run.story.email || run.story.reads.length > 0 || run.story.children.length > 0);
  return (
    <PageLayout
      icon={Workflow}
      title={definition.data?.name ?? run.workflowId}
      description={`Version ${run.version} · started ${relativeTime(run.createdAt)}`}
      badge={<RunStatus status={run.status} testId="run-status" />}
      backHref="/workflows/runs"
      actions={
        // The server says who may cancel (the starter, an admin or a reviewer); the button follows it.
        !TERMINAL_RUN.includes(run.status) && run.canCancel !== false && (
          <Button variant="outline" onClick={() => setCancelOpen(true)} data-testid="run-cancel">
            <CircleStop /> Cancel run
          </Button>
        )
      }
    >
      <RecordLayout
        rail={
          <AttributeCard title="Run" icon={Workflow} testId="run-attributes">
            {(
              [
                ['Outcome', run.outcomeText ?? '—'],
                ['Mode', run.mode],
                [
                  'Definition',
                  // The rail is narrow, so a long id shows in full on hover and copies in one click.
                  <span key="d" className="flex min-w-0 items-center gap-1">
                    <Link href={`/workflows/definitions/${encodeURIComponent(run.workflowId)}`} className="truncate underline underline-offset-2" title={`${run.workflowId} v${run.version}`}>
                      {`${run.workflowName ?? run.workflowId} v${run.version}`}
                    </Link>
                    <CopyIconButton value={run.workflowId} label="workflow id" />
                  </span>,
                ],
                ['Digest', <CopyId key="g" value={run.digest} label="digest" />],
                ['Finished', run.finishedAt ? relativeTime(run.finishedAt) : '—'],
                ['Started by', <StartedBy key="p" run={run} testId={parentRun ? 'run-parent' : 'run-started-by'} />],
                ...(files.length
                  ? ([['Files', <span key="f" className="flex flex-wrap gap-2" data-testid="run-files">{files.map((f) => <Link key={f.id} href={`/files?file=${f.id}`} title={f.id} className={f.name ? 'min-w-0 break-words text-sm underline underline-offset-2' : 'text-xs underline underline-offset-2'}>{f.name ?? <MiddleTruncate text={f.id} />}</Link>)}</span>]] as [string, React.ReactNode][])
                  : []),
                            ] as [string, React.ReactNode][]
              ).map(([label, value]) => (
                <FieldRow key={label} label={label} value={value} wrap />
              ))}
            </AttributeCard>
          }
        >
          <div className="flex flex-col gap-6">
            {run.error && (
              <Alert variant="destructive">
                <AlertTitle>The run failed</AlertTitle>
                <AlertDescription>{run.error}</AlertDescription>
              </Alert>
            )}
            {run.status === 'cancelled' && (
              <Alert data-testid="run-cancelled">
                <AlertTitle>Cancelled</AlertTitle>
                <AlertDescription>{run.finishedAt ? `Stopped ${relativeTime(run.finishedAt)}. ` : ''}No further step runs, and any review it was waiting on was withdrawn.</AlertDescription>
              </Alert>
            )}
            {run.result && (
              <Section title="Result" description={run.result.name ? `Ended at ${run.result.name}: ${run.outcomeText ?? run.result.outcome}` : (run.outcomeText ?? run.result.outcome)}>
                <div data-testid="run-result" data-outcome={run.result.outcome}>
                  {/* The story below tells what the run did; the result's own fields stay behind Raw. */}
                  <ReadableValue value={run.result.output ?? null} testId="run-result-value" rawOnly={told} />
                </div>
              </Section>
            )}
            {run.waiting && (
              <Alert data-testid="run-waiting">
                <AlertTitle>Waiting at {nodeName(run.waiting.node)}</AlertTitle>
                <AlertDescription className="flex flex-wrap items-center gap-2">
                  The run continues once a person decides this step.
                  {/* A runner review's id is the run, the step and its iteration, as Human Tasks lists it. */}
                  <Link href={`/reviews?review=${encodeURIComponent(`${run.id}:${run.waiting.node}:${run.waiting.iteration}`)}`} className="font-medium underline underline-offset-2" data-testid="run-open-review">
                    Open in Human Tasks
                  </Link>
                </AlertDescription>
              </Alert>
            )}
            {/* Its own steps reached an End, but a run it started has not finished: waiting on that run, not on a step. */}
            {!run.waiting && run.outcome && (run.status === 'waiting' || run.status === 'running') && (
              <Alert data-testid="run-waiting-on-runs">
                <AlertTitle>{run.status === 'waiting' ? 'Waiting on a run it started' : 'A run it started is still going'}</AlertTitle>
                <AlertDescription>Its own steps are done. It finishes when the last run it started ends. The list of runs it started shows where each one is.</AlertDescription>
              </Alert>
            )}
            {!!run.story?.lines?.length && <StoryFeed title="What happened" description="Each step of this run, oldest first." lines={run.story.lines} testId="run-story-feed" />}
            {run.story && <RunStoryView story={run.story} />}
            <Section title="Graph" description="The workflow as this run met it: what passed, failed or was skipped, and the paths it took. Click a step for its input and output.">
              {definition.isError || nodeTypes.isError ? (
                <QueryError
                  what="the workflow graph"
                  testId="run-graph-error"
                  onRetry={() => (definition.isError ? definition.refetch() : nodeTypes.refetch())}
                  retrying={definition.isFetching || nodeTypes.isFetching}
                  error={definition.error ?? nodeTypes.error}
                />
              ) : definition.data && nodeTypes.data ? (
                <RunCanvas definition={definition.data.definition} types={nodeTypes.data} steps={run.steps} runStatus={run.status} onOpenStep={setOpen} />
              ) : (
                <Skeleton className="h-112 w-full rounded-lg" data-testid="run-graph-loading" />
              )}
            </Section>
            <Section title={`Steps · ${run.steps.length}`} description="In the order they started; a step shows its last attempt." flush>
              <div className="p-2">
                <StepsTable steps={run.steps} nodeName={nodeName} onOpen={setOpen} />
              </div>
            </Section>
            {!!run.decisions?.length && (
              <Section title="Decisions" description="Who decided each Human Task in this run, when and why." flush>
                <Rows testId="run-decisions">
                  {run.decisions.map((d) => (
                    <Row
                      key={d.reviewId}
                      href={`/reviews/${encodeURIComponent(d.reviewId)}`}
                      title={nodeName(d.nodeId)}
                      // The decision leads the line under the step, so a narrow screen keeps it when the title is cut.
                      description={[`${words(d.action)}${d.by?.name ? ` by ${d.by.name}` : ''}`, d.at ? relativeTime(d.at) : null, d.reason].filter(Boolean).join(' · ')}
                      trailing={<span className="text-xs text-muted-foreground">Open task</span>}
                    />
                  ))}
                </Rows>
              </Section>
            )}
            <div className="grid gap-4 lg:grid-cols-2">
              <Section title="Input">
                <ReadableValue value={run.input ?? {}} testId="run-input" />
              </Section>
              <Section title="Output" description="What the End step returned">
                <ReadableValue value={run.output ?? null} testId="run-output" />
              </Section>
            </div>
          </div>
        </RecordLayout>
        <DialogShell
          open={cancelOpen}
          onOpenChange={(o) => {
            setCancelOpen(o);
            if (!o) setCancelError(undefined);
          }}
          size="sm"
          title="Cancel this run"
          description="No further step runs. A review it is waiting on is withdrawn from Reviews. A step already calling a system finishes that call."
          footer={
            <>
              <Button variant="outline" onClick={() => setCancelOpen(false)} disabled={cancel.isPending}>
                Keep running
              </Button>
              <LoadingButton
                variant="destructive"
                isLoading={cancel.isPending}
                loadingText="Cancelling…"
                data-testid="run-cancel-confirm"
                onClick={async () => {
                  try {
                    await cancel.mutateAsync(run.id);
                    setCancelOpen(false);
                  } catch (e) {
                    setCancelError(e instanceof Error ? e.message : 'The run was not cancelled');
                  }
                }}
              >
                Cancel run
              </LoadingButton>
            </>
          }
        >
          {cancelError ? <p className="text-sm text-destructive">{cancelError}</p> : <p className="text-sm text-muted-foreground">This cannot be undone; start a new run to try again.</p>}
        </DialogShell>
        <StepSheet
          step={step}
          nodeName={nodeName}
          onOpenChange={(o) => !o && setOpen(null)}
          navigation={open === null ? undefined : { currentIndex: open, totalCount: run.steps.length, onPrev: open > 0 ? () => setOpen(open - 1) : undefined, onNext: open < run.steps.length - 1 ? () => setOpen(open + 1) : undefined }}
        />
      </PageLayout>
    );
  }
