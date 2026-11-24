'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle } from 'lucide-react';

import { ScheduleForm, localTimeZone } from '@/components/shared/schedule-form';
import { formOf, ruleOf, type EveryFormValue } from '@/components/shared/schedule-forms/every-rule';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { LoadingButton } from '@/components/shared/loading-button';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useDefinition, useSetDefinitionPaused } from '@/hooks/engine-queries';
import { useCan } from '@/hooks/me-queries';
import { useClearSchedule, useSaveSchedule, useSchedulePreview } from '@/hooks/schedule-queries';
import { ApiError } from '@/lib/api/contract';
import { dateTime } from '@/lib/format';
import type { EveryRule, ScheduleView } from '@/lib/types/schedules';

import type { TriggerPanelProps } from './trigger-panels';

/** What the clock did with the last slot, in the words the panel shows. */
const OUTCOME: Record<NonNullable<ScheduleView['lastOutcome']>, string> = { ran: 'ran', late: 'ran late', skipped: 'skipped', refused: 'refused', missed: 'missed', seen: 'seen' };

const FIELDS = ['every', 'unit', 'start', 'days', 'between', 'tz'];

/** The refusal beside the field it names; one that names no field of this form (a required input) is shown above the form. */
function refusal(error: unknown): { byField: Record<string, string>; general?: string } {
  if (!(error instanceof ApiError)) return { byField: {}, general: error instanceof Error ? error.message : undefined };
  const field = String(error.details?.field ?? '');
  return FIELDS.includes(field) ? { byField: { [field]: error.message } } : { byField: {}, general: error.message };
}

/**
 * The Schedule trigger's panel in the step sheet's "How it starts" slot. A schedule is saved on its own, outside the
 * workflow's versions, so it applies at once to the live version and is not part of publish review; the panel says so.
 * Pause is the workflow's own, in the header, and stops the whole workflow.
 */
export function SchedulePanel({ node, workflowId }: TriggerPanelProps) {
  const view = useDefinition(workflowId);
  const schedule = view.data?.schedules?.find((s) => s.triggerStep === node.id);
  const mayEdit = useCan('workflows', 'edit') === true && useCan('deployments', 'create') === true;
  if (view.isPending) return <Skeleton className="h-48 w-full" data-testid="schedule-loading" />;
  // Keyed by the saved rule's words, so a change saved elsewhere (the API, the CLI) opens as it is.
  return <PanelBody key={schedule?.words ?? 'none'} node={node} workflowId={workflowId} schedule={schedule} paused={view.data?.paused ?? false} mayEdit={mayEdit} />;
}

function PanelBody({ node, workflowId, schedule, paused, mayEdit }: { node: TriggerPanelProps['node']; workflowId: string; schedule: ScheduleView | undefined; paused: boolean; mayEdit: boolean }) {
  const saved = schedule && schedule.rule.kind === 'every' ? (schedule.rule as EveryRule) : undefined;
  const [form, setForm] = React.useState<EveryFormValue>(() => formOf(saved, localTimeZone()));
  const [confirmClear, setConfirmClear] = React.useState(false);
  const rule = Number.isFinite(Number(form.every)) && form.every !== '' ? ruleOf(form) : null;
  const preview = useSchedulePreview(rule);
  const save = useSaveSchedule(workflowId, node.id);
  const clear = useClearSchedule(workflowId, node.id);
  const resume = useSetDefinitionPaused(workflowId);
  const refused = refusal(save.error ?? (preview.isError ? preview.error : null));
  const idle = schedule?.idleCode ?? null;
  const showsPaused = idle === 'paused';

  if (schedule && schedule.rule.kind !== 'every') {
    // A rule of a kind this form has no fields for: shown in words, never rewritten by a form that cannot hold it.
    return <ReadOnlyWords schedule={schedule} />;
  }
  return (
    <Section title="Schedule" description="Runs this workflow by itself." actions={<Badge variant="outline">Not part of a version</Badge>}>
      <div className="flex min-w-0 flex-col gap-4" data-testid="schedule-panel">
        <p className="text-sm text-muted-foreground">Applies at once to the live version when you save.{schedule ? ` Changed by ${schedule.changedByName || schedule.changedBy}, ${dateTime(schedule.changedAt)}.` : ''}</p>
        {idle === 'no_live_version' && (
          <Alert data-testid="schedule-alert-not-live">
            <AlertTriangle />
            <AlertTitle>Saved. Not running yet</AlertTitle>
            <AlertDescription>No version of this workflow is live. The schedule starts at its next time once a version is published.</AlertDescription>
          </Alert>
        )}
        {showsPaused && (
          <Alert data-testid="schedule-alert-paused">
            <AlertTriangle />
            <AlertTitle>Paused: no scheduled runs</AlertTitle>
            <AlertDescription>
              Pause stops the whole workflow, not just this schedule. Resume waits for the next time on the schedule.
              {mayEdit && (
                <Button size="sm" variant="outline" className="mt-2" disabled={resume.isPending} onClick={() => resume.mutate(false)} data-testid="schedule-resume">
                  Resume
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}
        {(idle === 'step_missing' || idle === 'not_schedulable') && schedule && (
          <Alert data-testid="schedule-alert-idle">
            <AlertTriangle />
            <AlertTitle>Saved but not running</AlertTitle>
            <AlertDescription>{schedule.idle}</AlertDescription>
          </Alert>
        )}
        {refused.general && (
          <Alert variant="destructive" data-testid="schedule-refusal">
            <AlertTriangle />
            <AlertTitle>The schedule was not saved</AlertTitle>
            <AlertDescription>{refused.general}</AlertDescription>
          </Alert>
        )}
        <ScheduleForm
          value={form}
          onChange={setForm}
          errors={refused.byField}
          disabled={!mayEdit}
          idPrefix={`schedule-${node.id}`}
          preview={preview.data}
          previewing={preview.isFetching}
          nextRunsNote={showsPaused ? 'None while paused' : undefined}
        />
        {schedule && <LastRun schedule={schedule} />}
        {mayEdit ? (
          <div className="flex flex-wrap gap-2">
            <LoadingButton isLoading={save.isPending} loadingText="Saving…" disabled={rule === null} onClick={() => rule && save.mutate(rule)} data-testid="schedule-save">
              Save schedule
            </LoadingButton>
            {schedule && (
              <Button variant="outline" onClick={() => setConfirmClear(true)} data-testid="schedule-clear">
                Clear schedule
              </Button>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">You can read this schedule. Saving or clearing it needs the right to edit the workflow and to add deployments.</p>
        )}
      </div>
      <DeleteDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        entityType="schedule"
        verb="Clear"
        description="Scheduled runs stop. Runs already started carry on. The workflow itself is not paused."
        isLoading={clear.isPending}
        onConfirm={async () => {
          await clear.mutateAsync();
          setConfirmClear(false);
        }}
        testIdPrefix="schedule-clear"
      />
    </Section>
  );
}

function LastRun({ schedule }: { schedule: ScheduleView }) {
  return (
    <div className="flex flex-col gap-1" data-testid="schedule-last-run">
      <p className="text-sm font-medium">Last scheduled run</p>
      {schedule.lastOutcome && schedule.lastSlotAt ? (
        <p className="text-sm text-muted-foreground">
          {dateTime(schedule.lastSlotAt)} · {OUTCOME[schedule.lastOutcome]}
          {schedule.lastOutcomeReason ? `: ${schedule.lastOutcomeReason}` : ''}
          {schedule.lastRunId && (
            <>
              {' '}
              <Link href={`/build/runs/${encodeURIComponent(schedule.lastRunId)}`} className="underline underline-offset-2">
                Open the run
              </Link>
            </>
          )}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">Not run yet.</p>
      )}
    </div>
  );
}

function ReadOnlyWords({ schedule }: { schedule: ScheduleView }) {
  return (
    <Section title="Schedule" description={schedule.words}>
      <ul className="text-sm tabular-nums">
        {schedule.nextRuns.map((t) => (
          <li key={t}>{dateTime(t)}</li>
        ))}
      </ul>
      <LastRun schedule={schedule} />
    </Section>
  );
}
