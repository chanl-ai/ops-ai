'use client';

import type { ReactNode } from 'react';
import { FlaskConical } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import type { WorkflowRun } from '@/lib/types/domain';

import { RunTrace } from './run-trace';

/**
 * One run's step trace in a sheet. The workflow Runs tab and the Cases page both open runs here, so a run reads
 * the same in either place; `summary` adds page-specific context above the trace.
 */
export function RunSheet({
  run,
  onClose,
  navigation,
  summary,
  onSaveAsTest,
  saving,
}: {
  run: WorkflowRun | null;
  onClose: () => void;
  navigation?: DetailSheetNavigation;
  summary?: ReactNode;
  onSaveAsTest?: (run: WorkflowRun) => void;
  saving?: boolean;
}) {
  return (
    <DetailSheet
      open={!!run}
      onOpenChange={(o) => !o && onClose()}
      title={run ? `${run.id} · ${run.subject}` : ''}
      description={run ? `Started ${relativeTime(run.startedAt)}` : undefined}
      navigation={run ? navigation : undefined}
      testId="run-sheet"
      scrollKey={run?.id}
      footerActions={
        run &&
        onSaveAsTest && (
          <Button size="sm" variant="outline" disabled={saving} onClick={() => onSaveAsTest(run)}>
            <FlaskConical className="size-3.5" /> Save as test case
          </Button>
        )
      }
    >
      {run && (
        <div className="flex flex-col gap-5">
          {summary}
          <RunTrace run={run} />
        </div>
      )}
    </DetailSheet>
  );
}
