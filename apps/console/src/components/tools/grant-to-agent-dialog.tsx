'use client';

import * as React from 'react';
import { Bot } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FormFieldGroup } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { agentOptions } from '@/hooks/options-queries';
import { useGrantToolToAgent } from '@/hooks/queries';

/**
 * Grant one tool to an agent, picked from the team's agents. It saves the agent as its own page's Grant tools does: a
 * new draft version, used once that version is published.
 */
export function GrantToAgentDialog({ tool, onOpenChange }: { tool: { id: string; title: string } | null; onOpenChange: (open: boolean) => void }) {
  const [agentId, setAgentId] = React.useState<string[]>([]);
  const grant = useGrantToolToAgent();
  const close = () => {
    setAgentId([]);
    onOpenChange(false);
  };
  const save = () =>
    tool &&
    grant.mutate(
      { agentId: agentId[0], toolId: tool.id },
      {
        onSuccess: (agent) => {
          toast.success(`Granted ${tool.title} to ${agent.name}`, { description: 'Saved as a draft version of the agent. Publish it to use the tool live.' });
          close();
        },
        onError: (e) => toast.error(`Couldn’t grant ${tool.title}`, { description: e.message }),
      },
    );
  return (
    <DialogShell
      open={tool !== null}
      onOpenChange={(o) => !o && close()}
      size="sm"
      title={tool ? `Grant ${tool.title} to an agent` : 'Grant to an agent'}
      description="The agent may call it once you publish the agent's new version."
      data-testid="grant-tool-dialog"
      footer={
        <>
          <Button variant="outline" onClick={close}>
            Cancel
          </Button>
          <LoadingButton isLoading={grant.isPending} disabled={!agentId.length} onClick={save} data-testid="grant-tool-save">
            Grant
          </LoadingButton>
        </>
      }
    >
      <FormFieldGroup label="Agent">
        <EntityPicker
          source={agentOptions}
          value={agentId}
          onChange={setAgentId}
          multiple={false}
          addLabel="Choose an agent"
          searchPlaceholder="Search agents…"
          emptyText="No agent matches."
          icon={Bot}
          testId="grant-tool-agent"
        />
      </FormFieldGroup>
    </DialogShell>
  );
}
