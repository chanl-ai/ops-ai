'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ScheduleForm } from '@/components/shared/schedule-form';
import { formOf, ruleOf, type EveryFormValue } from '@/components/shared/schedule-forms/every-rule';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useCreateScheduledWorkflow, useSchedulePreview } from '@/hooks/schedule-queries';
import { starterDefinition } from '@/components/workflows/definition-editor/starter';
import { localTimeZone } from '@/lib/format';
import { refusalOf, SCHEDULE_FIELDS } from '@/lib/schedule-refusal';
import type { EngineDefinition } from '@/lib/types/engine';

/** A workflow with one Schedule trigger, the agent as its one step, and the two ways that step can end. */
function workflowFor(name: string, agentId: string, prompt: string): EngineDefinition {
  const { id } = starterDefinition(name, '');
  return {
    schemaVersion: 2,
    id,
    name,
    nodes: [
      { id: 'start', type: 'ops.trigger.schedule', typeVersion: 1, name: 'On a schedule', parameters: {} },
      { id: 'ask', type: 'ops.ai.agent', typeVersion: 1, name: 'Ask the agent', parameters: { agent: agentId, prompt } },
      { id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: { outcome: 'done' } },
      { id: 'failed', type: 'ops.flow.end', typeVersion: 1, name: 'Failed', parameters: { outcome: 'failed', result: 'failed' } },
    ],
    connections: [
      { from: { node: 'start', port: 'payload' }, to: { node: 'ask', port: 'in' } },
      { from: { node: 'ask', port: 'ok' }, to: { node: 'done', port: 'in' } },
      { from: { node: 'ask', port: 'error' }, to: { node: 'failed', port: 'in' } },
    ],
  };
}

/**
 * "Schedule an agent": makes a workflow whose one step is the agent, saves the schedule on its trigger, and opens it in the
 * editor. There is no agent schedule route; the workflow is how an agent runs on a schedule, and it runs once published.
 */
export function ScheduleAgentDialog({ open, onOpenChange, agentId, agentName }: { open: boolean; onOpenChange: (open: boolean) => void; agentId: string; agentName: string }) {
  const router = useRouter();
  const [name, setName] = React.useState('');
  const [prompt, setPrompt] = React.useState('');
  const [form, setForm] = React.useState<EveryFormValue>(() => formOf(undefined, localTimeZone()));
  const [problem, setProblem] = React.useState<{ byField: Record<string, string>; general?: string }>({ byField: {} });
  const rule = Number.isFinite(Number(form.every)) && form.every !== '' ? ruleOf(form) : null;
  const preview = useSchedulePreview(rule);
  const create = useCreateScheduledWorkflow();
  const fromPreview = preview.isError ? refusalOf(preview.error).byField : {};
  const canCreate = name.trim() !== '' && prompt.trim() !== '' && rule !== null && !preview.isError;

  const submit = () => {
    if (!rule) return;
    setProblem({ byField: {} });
    create.mutate(
      { definition: workflowFor(name.trim(), agentId, prompt.trim()), rule },
      {
        onSuccess: ({ workflowId, saveError }) => {
          if (saveError) toast.error(`The workflow was made, but its schedule was not saved: ${saveError}`);
          else toast.success('Workflow made. Publish it to start the schedule.');
          onOpenChange(false);
          router.push(`/build/workflows/${encodeURIComponent(workflowId)}`);
        },
        onError: (e) => {
          const refused = refusalOf(e);
          setProblem(refused.general || Object.keys(refused.byField).length ? refused : { byField: {}, general: 'The workflow was not made.' });
        },
      },
    );
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title="Schedule an agent"
      description={`Makes a workflow that asks ${agentName} on a schedule. It runs once the workflow is published.`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton isLoading={create.isPending} loadingText="Creating…" disabled={!canCreate} onClick={submit} data-testid="schedule-agent-create">
            Create workflow
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-4" data-testid="schedule-agent-dialog">
        {problem.general && (
          <Alert variant="destructive">
            <AlertDescription>{problem.general}</AlertDescription>
          </Alert>
        )}
        <FormField id="schedule-agent-name" label="Workflow name">
          <Input id="schedule-agent-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Morning report" />
        </FormField>
        <FormField id="schedule-agent-prompt" label="Ask the agent">
          <Textarea id="schedule-agent-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="e.g. Summarise yesterday's held wires." />
        </FormField>
        <ScheduleForm value={form} onChange={setForm} errors={{ ...fromPreview, ...problem.byField }} idPrefix="schedule-agent" preview={preview.data} previewing={preview.isFetching} />
      </div>
    </DialogShell>
  );
}
