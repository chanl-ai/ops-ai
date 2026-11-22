'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useAgentPrompt } from '@/hooks/queries';

/**
 * The brief card's "View prompt": the exact text the model receives for this version, read only, as the service
 * assembles it (`GET /v1/agents/{id}/prompt`), so Never is the last section. Nothing here edits the prompt.
 */
export function ViewPromptDialog({ agentId, version, name }: { agentId: string; version: number; name: string }) {
  const [open, setOpen] = React.useState(false);
  const prompt = useAgentPrompt(agentId, version, open);
  return (
    <>
      <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)} data-testid="agent-view-prompt">
        View prompt
      </Button>
      <DialogShell
        open={open}
        onOpenChange={setOpen}
        size="lg"
        title={`Prompt for ${name}`}
        description={<>What the model receives from v{version}, read only. Never is applied last, on every reply. The platform&rsquo;s own rules and any running skill step are added by each turn.</>}
      >
        {prompt.isPending ? (
          <Skeleton className="h-64 w-full" />
        ) : prompt.isError ? (
          <QueryError what="the prompt" error={prompt.error} onRetry={() => prompt.refetch()} retrying={prompt.isFetching} />
        ) : (
          <pre className="rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap" data-testid="agent-prompt-text">
            {prompt.data.text}
          </pre>
        )}
      </DialogShell>
    </>
  );
}
