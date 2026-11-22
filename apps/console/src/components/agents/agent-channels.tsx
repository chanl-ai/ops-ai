'use client';

import * as React from 'react';
import { Code2, Mail, MessageSquare, MessagesSquare, Plug, Send, Users } from 'lucide-react';

import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { CodeBlock } from '@/components/deployments/deployment-meta';
import { CopyField } from '@/components/shared/setting/copy-field';
import { Row, Rows, Section } from '@/components/shared/surface';
import { LiveBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAgentsApiUrl, useWidgetDeployments } from '@/hooks/widget-deployment-queries';
import { useCanSetDefaultAgent, useDefaultAgent } from '@/hooks/chat-queries';
import type { Agent } from '@/lib/types/domain';

type Reach = 'On' | 'Off' | 'Not set up';

function ReachState({ state, testId }: { state: Reach; testId: string }) {
  return (
    <Badge variant={state === 'On' ? 'secondary' : 'outline'} data-testid={testId}>
      {state}
    </Badge>
  );
}

/** The four ways to call the agent from code, each built from the SDKs' own methods (agents.chat, `opsai agents chat`). */
export function agentSnippets(agentId: string, base: string) {
  const question = 'Where is my request?';
  return {
    curl: `# Start a thread on the published agent, then send it a message.\ncurl -X POST ${base}/threads \\\n  -H "Authorization: Bearer $OPS_API_KEY" -H "X-Team-Id: $OPS_TEAM" \\\n  -H "Content-Type: application/json" \\\n  -d '{ "graph": "agent:${agentId}" }'\n\ncurl -N -X POST ${base}/threads/$THREAD_ID/runs/stream \\\n  -H "Authorization: Bearer $OPS_API_KEY" -H "X-Team-Id: $OPS_TEAM" \\\n  -H "Content-Type: application/json" \\\n  -d '{ "input": { "message": "${question}" } }'`,
    python: `from ops_ai import OpsAI\n\nops = OpsAI()  # reads OPS_BASE_URL, OPS_API_KEY and OPS_TEAM\nreply = ops.agents.chat("${agentId}", "${question}")\nprint(reply["reply"])`,
    typescript: `import { OpsAI } from '@chanl-ai/ops-ai';\n\nconst ops = new OpsAI(); // reads OPS_BASE_URL, OPS_API_KEY and OPS_TEAM\nconst { reply } = await ops.agents.chat('${agentId}', '${question}');\nconsole.log(reply);`,
    cli: `opsai agents chat ${agentId} --message "${question}"`,
  };
}

/**
 * The Channels tab: one list of every way people reach the agent, each with a state word and at most one action.
 * Email comes from the workflows that run the agent (`usedIn`, joined by agents-service with each workflow's channel);
 * MCP links offer workflows and tools, not one agent, and Slack and Teams have no trigger yet, so those rows say so
 * with no action.
 */
export function AgentChannels({ agent, onNewEmbed }: { agent: Agent; onNewEmbed?: () => void }) {
  const current = useDefaultAgent();
  const isAdmin = useCanSetDefaultAgent();
  const embeds = useWidgetDeployments(agent.id);
  const [defaultOpen, setDefaultOpen] = React.useState(false);
  const [apiOpen, setApiOpen] = React.useState(false);
  const published = agent.availability === 'published';
  const isDefault = current.data?.agentId === agent.id;
  const email = agent.usedIn.filter((u) => !u.own && u.channel === 'email');
  const liveEmbeds = embeds.data?.some((e) => !e.paused) ?? false;
  const base = useAgentsApiUrl();
  const snippets = agentSnippets(agent.id, base);
  return (
    <Section title="Ways to reach it" description="Chat, the API and embeds use the published version. Workflows each run the version they pin." flush>
      <Rows>
        <Row
          leading={<MessagesSquare className="size-4 text-muted-foreground" />}
          title="Chat"
          description={isDefault ? 'New chats start here.' : current.data?.agentName ? `Everyone in the team can pick it. New chats start on ${current.data.agentName}.` : 'Everyone in the team can pick it.'}
          trailing={
            <span className="flex items-center gap-2">
              <ReachState state={published ? 'On' : 'Off'} testId="agent-channel-chat" />
              {isDefault ? <Badge variant="secondary">Default</Badge> : isAdmin && published ? <Button size="sm" variant="outline" onClick={() => setDefaultOpen(true)}>Make default</Button> : null}
            </span>
          }
        />
        <Row
          leading={<Code2 className="size-4 text-muted-foreground" />}
          title="API and SDK"
          description="Call it from your own code, the SDK or the command line, with an API key made in Settings."
          trailing={
            <span className="flex items-center gap-2">
              <ReachState state={published ? 'On' : 'Off'} testId="agent-channel-api" />
              <Button size="sm" variant="outline" onClick={() => setApiOpen((o) => !o)} aria-expanded={apiOpen} data-testid="agent-channel-api-toggle">
                {apiOpen ? 'Hide' : 'Show'}
              </Button>
            </span>
          }
        >
          {apiOpen && (
            <div className="flex min-w-0 flex-col gap-3 pt-2" data-testid="agent-channel-api-detail">
              <CopyField id="ag-id" value={agent.id} label="agent ID" />
              <CodeBlock label="Endpoint" code={`${base}/threads`} />
              <Tabs defaultValue="curl">
                <TabsList>
                  <TabsTrigger value="curl">curl</TabsTrigger>
                  <TabsTrigger value="python">Python SDK</TabsTrigger>
                  <TabsTrigger value="typescript">TypeScript SDK</TabsTrigger>
                  <TabsTrigger value="cli">CLI</TabsTrigger>
                </TabsList>
                {(['curl', 'python', 'typescript', 'cli'] as const).map((k) => (
                  <TabsContent key={k} value={k}>
                    <CodeBlock label={k === 'curl' ? 'Request' : k === 'cli' ? 'Command' : 'Example'} code={snippets[k]} />
                  </TabsContent>
                ))}
              </Tabs>
            </div>
          )}
        </Row>
        <Row
          leading={<Plug className="size-4 text-muted-foreground" />}
          title="MCP"
          description="An MCP link offers tools and published workflows, not one agent. Add the agent as a step in a workflow, then add that workflow to a link."
          trailing={<ReachState state="Not set up" testId="agent-channel-mcp" />}
        />
        <Row
          leading={<Send className="size-4 text-muted-foreground" />}
          title="Embed on a page"
          description={embeds.isPending ? 'Checking embeds…' : liveEmbeds ? 'A chat window on other sites; each embed is listed below.' : 'A chat window on your intranet or another site.'}
          trailing={
            <span className="flex items-center gap-2">
              <ReachState state={liveEmbeds ? 'On' : 'Not set up'} testId="agent-channel-embed" />
              {onNewEmbed && agent.canEdit !== false && (
                <Button size="sm" variant="outline" onClick={onNewEmbed} data-testid="embed-agent">
                  New
                </Button>
              )}
            </span>
          }
        />
        {email.length ? (
          email.map((u) => (
            <Row
              key={u.workflowId}
              href={`/build/workflows/${u.workflowId}`}
              leading={<Mail className="size-4 text-muted-foreground" />}
              title="Email"
              description={`Through the workflow ${u.workflowName}.`}
              trailing={<ReachState state={u.status === 'live' ? 'On' : 'Off'} testId="agent-channel-email" />}
            />
          ))
        ) : (
          <Row
            leading={<Mail className="size-4 text-muted-foreground" />}
            title="Email"
            description="No workflow started by an email runs this agent yet."
            trailing={<ReachState state="Not set up" testId="agent-channel-email" />}
          />
        )}
        <Row
          leading={<MessageSquare className="size-4 text-muted-foreground" />}
          title="Slack"
          description="No workflow can start from a Slack message yet."
          trailing={<ReachState state="Not set up" testId="agent-channel-slack" />}
        />
        <Row
          leading={<Users className="size-4 text-muted-foreground" />}
          title="Teams"
          description="No workflow can start from a Teams message yet."
          trailing={<ReachState state="Not set up" testId="agent-channel-teams" />}
        />
      </Rows>
      <MakeDefaultAgentDialog agent={agent} open={defaultOpen} onOpenChange={setDefaultOpen} />
    </Section>
  );
}
