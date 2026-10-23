'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { StepUpCancelled, useStepUpGate } from '@/components/auth/reauth-dialog';
import { OpsCard } from '@/components/chat/ops-card';
import { LoadingButton } from '@/components/shared/loading-button';
import { RunInputForm } from '@/components/workflows/run-input-form';
import { useStartWorkflow } from '@/hooks/engine-queries';
import { useDecideReview } from '@/hooks/queries';
import { caseCard, missingCard, runCard, startCard, taskCard, taskDecision } from '@/lib/ops-card-mappers';
import type { CaseRecordDetail } from '@/lib/types/case-records';
import type { Review, ReviewDecision } from '@/lib/types/domain';
import type { DefinitionView, EngineRunDetail } from '@/lib/types/engine';
import type { CardButton, OpsCardRef } from '@/lib/types/ops-card';

/**
 * One card reference from an Ops tool, filled in by the thread read (c-469), drawn as the record's card. Buttons do
 * what the record's own page does, as the signed-in person: a Human Task is decided through the decision route with
 * the step-up /reviews asks for, a workflow starts from its trigger's start form. `readOnly` (the embedded chat, whose
 * widget API serves no record routes) draws the card with Open and no buttons. `onActed` runs once a press is recorded,
 * so the conversation reads the thread again and the card redraws from the record's new state.
 */
export function RecordCard({ cardRef, readOnly = false, onActed }: { cardRef: OpsCardRef; readOnly?: boolean; onActed?: () => void }) {
  if (cardRef.missing || cardRef.view == null) return <OpsCard spec={missingCard(cardRef)} />; // the caller shows an unfilled one as loading
  if (cardRef.type === 'case') return <OpsCard spec={caseCard(cardRef.view as CaseRecordDetail)} />;
  if (cardRef.type === 'run') return <OpsCard spec={runCard(cardRef.view as EngineRunDetail)} />;
  if (cardRef.type === 'task') return <TaskCard review={cardRef.view as Review} readOnly={readOnly} onActed={onActed} />;
  return <StartCard definition={cardRef.view as DefinitionView} readOnly={readOnly} onActed={onActed} />;
}

function TaskCard({ review, readOnly, onActed }: { review: Review; readOnly: boolean; onActed?: () => void }) {
  const decide = useDecideReview();
  const stepUp = useStepUpGate();
  const [outcome, setOutcome] = React.useState<string>();
  const run = async (decision: ReviewDecision, word: string) => {
    try {
      await stepUp.withStepUp(`${word} “${review.title}”`, (stepUpToken) => decide.mutateAsync({ id: review.id, decision, stepUpToken }), { upfront: !!review.stepUp });
    } catch (e) {
      if (e instanceof StepUpCancelled) return;
      toast.error(`Couldn’t ${word.toLowerCase()} the task`, { description: e instanceof Error ? e.message : undefined });
      return;
    }
    setOutcome(`${word === 'Approve' ? 'Approved' : 'Rejected'} by you. The workflow carries on from here.`);
    onActed?.();
  };
  const buttons: CardButton[] =
    !readOnly && taskDecision(review) === 'buttons'
      ? [
          { id: 'approve', label: 'Approve', primary: true, locked: !!review.stepUp, onPress: () => run('approved', 'Approve') },
          { id: 'reject', label: 'Reject', onPress: () => run('rejected', 'Reject') },
        ]
      : [];
  return (
    <>
      <OpsCard spec={taskCard(review)} buttons={buttons} outcome={outcome} />
      {stepUp.dialog}
    </>
  );
}

function StartCard({ definition, readOnly, onActed }: { definition: DefinitionView; readOnly: boolean; onActed?: () => void }) {
  const start = useStartWorkflow();
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [error, setError] = React.useState<string>();
  const [outcome, setOutcome] = React.useState<string>();
  const form = definition.startForm;
  const go = async () => {
    setError(undefined);
    try {
      await start.mutateAsync({ workflowId: definition.workflowId, values });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The run did not start.');
      return;
    }
    setOutcome('Started. The run is under way; ask about it to follow it here.');
    onActed?.();
  };
  return (
    <OpsCard spec={startCard(definition)} outcome={outcome}>
      {form && !readOnly && !outcome && (
        <div className="flex flex-col gap-3" data-testid="ops-card-start-form">
          <RunInputForm schema={form.schema} value={values} onChange={setValues} error={error} />
          <LoadingButton size="sm" className="self-end" isLoading={start.isPending} onClick={() => void go()} data-testid="ops-card-action-start">
            {form.action || 'Start'}
          </LoadingButton>
        </div>
      )}
    </OpsCard>
  );
}
