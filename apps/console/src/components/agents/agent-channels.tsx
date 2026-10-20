'use client';

import * as React from 'react';
import { MessagesSquare, Route } from 'lucide-react';

import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { Row, Rows, Section } from '@/components/shared/surface';
import { LiveBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useCanSetDefaultAgent, useDefaultAgent } from '@/hooks/chat-queries';
import type { Agent } from '@/lib/types/domain';

/** The workflows that call the agent as a step (agents-service `usedIn`), its own one-step workflow left out. */
export function AgentWorkflowChannels({ agent }: { agent: Agent }) {
  const callers = agent.usedIn.filter((u) => !u.own);
  return (
    <Section title="Workflows that call it" description="Each runs the version it pins, so publishing the agent does not change a live workflow until it is republished." flush>
      {callers.length ? (
        <Rows>
          {callers.map((u) => (
            <Row
              key={u.workflowId}
              href={`/workflows/${u.workflowId}`}
              leading={<Route className="size-4 text-muted-foreground" />}
              title={u.workflowName}
              description={`Pins v${u.pinnedVersion}`}
              trailing={<LiveBadge status={u.status} />}
            />
          ))}
        </Rows>
      ) : (
        <p className="p-4 text-sm text-muted-foreground" data-testid="agent-workflow-channels-empty">
          No workflow calls {agent.name} yet. Add it as a step on a workflow&apos;s canvas.
        </p>
      )}
    </Section>
  );
}

/** Whether new chats in the team start on this agent (c-174), and the way to make it so for a team admin. */
export function AgentChatChannel({ agent }: { agent: Agent }) {
  const current = useDefaultAgent();
  const isAdmin = useCanSetDefaultAgent();
  const [open, setOpen] = React.useState(false);
  const isDefault = current.data?.agentId === agent.id;
  const published = agent.availability === 'published';
  return (
    <Section title="Chat" description="Everyone in the team can chat with a published agent; the team default is where a new chat starts." flush>
      {current.isPending ? (
        <Skeleton className="m-4 h-10" />
      ) : (
        <Rows>
          <Row
            leading={<MessagesSquare className="size-4 text-muted-foreground" />}
            title={isDefault ? `${agent.name} is the team's default` : published ? 'Available in chat' : 'Not in chat until published'}
            description={
              isDefault
                ? 'New chats start here, and it can ask the team’s other agents.'
                : current.data?.agentName
                  ? `New chats start on ${current.data.agentName}; people reach ${agent.name} by picking it or with @.`
                  : 'The team has no default agent, so people pick one when they start a chat.'
            }
            trailing={
              <span data-testid="agent-chat-channel">
                {isDefault ? (
                  <Badge variant="secondary">Default</Badge>
                ) : isAdmin && published ? (
                  <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
                    Make default
                  </Button>
                ) : null}
              </span>
            }
          />
        </Rows>
      )}
      <MakeDefaultAgentDialog agent={agent} open={open} onOpenChange={setOpen} />
    </Section>
  );
}
