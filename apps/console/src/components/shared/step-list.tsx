'use client';

import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';

import { Task, TaskContent, TaskItem, TaskTrigger } from '@/components/ai-elements/task';

export type StepListState = 'pending' | 'running' | 'done' | 'failed';

const ICON = {
  pending: <Circle className="size-4 text-muted-foreground" />,
  running: <Loader2 className="size-4 animate-spin text-muted-foreground" />,
  done: <CheckCircle2 className="size-4 text-success-text" />,
  failed: <XCircle className="size-4 text-destructive" />,
};

/** A plan or a run's steps, each with its state, on AI Elements' Task; open by default. */
export function StepList({ title, steps }: { title: string; steps: { title: string; state: StepListState }[] }) {
  return (
    <Task data-testid="step-list">
      <TaskTrigger title={title} />
      <TaskContent>
        <div className="mt-3 flex flex-col gap-2 border-l-2 pl-4">
          {steps.map((s, i) => (
            <TaskItem key={`${i}-${s.title}`} className="flex items-center gap-2" data-state={s.state}>
              {ICON[s.state]}
              <span className={s.state === 'done' ? 'text-muted-foreground' : undefined}>{s.title}</span>
            </TaskItem>
          ))}
        </div>
      </TaskContent>
    </Task>
  );
}
